import hashlib
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from pathlib import Path

from m3talist import audio, catalog, naming, ordering, profile, tags
from m3talist.artwork import calibration_set, to_baseline_jpeg
from m3talist.config import CALIBRATE_DIR, INPUT_DIR, OUTPUT_DIR, WORK_DIR
from m3talist.enrich import Enricher
from m3talist.models import AUDIO_SUFFIXES, FAILED, BuildResult, Release, Track


@dataclass
class ScanResult:
    releases: int = 0
    tracks: int = 0
    needs_review: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def _album_dirs(input_dir: Path) -> tuple[list[Path], list[str]]:
    albums, skipped = [], []
    for entry in sorted(input_dir.iterdir()):
        if entry.is_file():
            skipped.append(f"{entry.name}: loose file, must live in a subfolder")
            continue
        if not entry.is_dir():
            continue
        audio_files = [p for p in entry.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES]
        if audio_files:
            albums.append(entry)
        elif any(p.is_dir() for p in entry.iterdir()):
            skipped.append(f"{entry.name}: nested folders are out of scope")
        else:
            skipped.append(f"{entry.name}: no audio files")
    return albums, skipped


SIGNATURE_KEY = "input_signature"


def input_signature(input_dir: Path = INPUT_DIR) -> str:
    """Cheap fingerprint of the input tree: name, size and mtime of every file.

    Walking ~500 files costs a couple of milliseconds, so this can run on every
    page render. That beats a background watcher, which burns cycles with nobody
    looking and still misses edits made while the app was not running.
    """
    parts = []
    for path in sorted(input_dir.rglob("*")) if input_dir.exists() else []:
        if path.suffix.lower() in AUDIO_SUFFIXES and path.is_file():
            stat = path.stat()
            parts.append(f"{path}|{stat.st_size}|{stat.st_mtime_ns}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def input_changed(conn, input_dir: Path = INPUT_DIR) -> bool:
    recorded = catalog.get_meta(conn, SIGNATURE_KEY)
    return recorded is not None and recorded != input_signature(input_dir)


def _read_track(path: Path) -> Track:
    meta = tags.read(path)
    return Track(
        source_path=path,
        title=meta["title"] or path.stem,
        artist=meta["artist"],
        album_artist=meta["album_artist"],
        album=meta["album"],
        disc_no=meta["disc_no"],
        track_no=meta["track_no"] or naming.track_no_from_filename(path),
        year=meta["year"],
        genre=meta["genre"],
        audio=audio.probe(path),
    )


def _release_from(album_dir: Path, tracks: list[Track], artist_override: str | None) -> Release:
    def common(attribute: str) -> str | None:
        values = {getattr(t, attribute) for t in tracks if getattr(t, attribute)}
        return values.pop() if len(values) == 1 else None

    artist = artist_override or common("album_artist") or common("artist") or album_dir.name
    years = [t.year for t in tracks if t.year]
    return Release(
        artist=artist,
        title=common("album") or album_dir.name,
        source_dir=album_dir,
        year=min(years) if years else None,
    )


def scan(conn, input_dir: Path = INPUT_DIR, artists: dict[str, str] | None = None,
         on_progress=None, fresh: bool = False, force_alpha: bool = False) -> ScanResult:
    """Read the input tree into the catalog, then assign the global order.

    A rescan is additive: add_release/add_track upsert in place, so a manual
    track order set through the review screen survives. Pass fresh=True to
    wipe the catalog first instead.
    """
    audio.ensure_tools()
    if fresh:
        catalog.reset(conn)
    albums, skipped = _album_dirs(input_dir)
    result = ScanResult(skipped=skipped)
    seen: set[str] = set()

    for position, album_dir in enumerate(albums, start=1):
        paths = sorted(p for p in album_dir.iterdir() if p.suffix.lower() in AUDIO_SUFFIXES)
        tracks = [_read_track(path) for path in paths]
        release = _release_from(album_dir, tracks, (artists or {}).get(album_dir.name))
        release_id = catalog.add_release(conn, release)
        for track in tracks:
            catalog.add_track(conn, track, release_id)
            seen.add(str(track.source_path))
        result.releases += 1
        result.tracks += len(tracks)
        if on_progress:
            on_progress(position, len(albums), album_dir.name)

    # An empty input tree is far more likely to be a mistake — wrong path, drive
    # not mounted yet — than a deliberate request to forget the whole library.
    if seen:
        catalog.prune(conn, seen)
    elif albums:
        result.skipped.append("input holds no readable audio; catalog left untouched")
    catalog.set_meta(conn, SIGNATURE_KEY, input_signature(input_dir))
    conn.commit()
    result.needs_review = ordering.assign(conn, force_alpha=force_alpha)
    return result


def enrich(conn, settings=None, on_progress=None) -> dict[int, Path]:
    """Fill gaps from MusicBrainz and cache covers. Returns release_id -> cover file.

    Network is optional at every step: a lookup that fails leaves the release
    exactly as the local tags described it.
    """
    settings = settings or profile.load()
    covers_dir = WORK_DIR / "covers"
    covers_dir.mkdir(parents=True, exist_ok=True)
    covers: dict[int, Path] = {}
    releases = catalog.releases(conn)

    with Enricher(conn, settings) as enricher:
        for position, release in enumerate(releases, start=1):
            match = enricher.lookup_release(release.artist, release.title)
            if match:
                catalog.set_release_mbid(conn, release.id, match.get("mbid"), match.get("year"))
                if match.get("genre"):
                    catalog.fill_missing_genre(conn, release.id, match["genre"])
            cover = _cover_for(enricher, release, match, settings, covers_dir)
            if cover:
                covers[release.id] = cover
                catalog.set_release_cover(conn, release.id, cover)
            if on_progress:
                on_progress(position, len(releases), f"{release.artist} - {release.title}")

    conn.commit()
    return covers


def _cover_key(release: Release, mbid: str | None) -> str:
    """A stable identity for the cache file. SQLite reassigns release.id after
    a rescan drops a release, so the key must not depend on it."""
    if mbid:
        return mbid
    digest = hashlib.sha256(f"{release.artist}|{release.title}".encode("utf-8")).hexdigest()
    return digest[:16]


def _cover_for(enricher, release, match, settings, covers_dir: Path) -> Path | None:
    if not settings.cover_enabled:
        return None
    mbid = (match or {}).get("mbid") or release.mbid
    cached = covers_dir / f"{_cover_key(release, mbid)}.jpg"
    if cached.exists():
        return cached
    raw = enricher.fetch_cover(mbid) if mbid else None
    if not raw:
        return None
    resized = to_baseline_jpeg(raw, settings.cover_max_px)
    if not resized:
        return None
    cached.write_bytes(resized)
    return cached


def stored_covers(conn) -> dict[int, Path]:
    """Covers already on disk, so a build works with no network at all."""
    covers = {}
    for release in catalog.releases(conn):
        if release.cover_path and Path(release.cover_path).exists():
            covers[release.id] = Path(release.cover_path)
    return covers


@dataclass
class _Job:
    track: Track
    release: Release
    temp_path: Path
    total_tracks: int
    total_discs: int | None
    cover_path: Path | None


def _transcode_and_tag(job: _Job) -> tuple[int, str, str | None]:
    """Runs in a worker process. Transcode and tag in the staging area only."""
    try:
        status = audio.prepare(job.track.source_path, job.temp_path, job.track.audio)
        cover = job.cover_path.read_bytes() if job.cover_path else None
        tags.write(job.temp_path, job.track, job.release,
                   job.total_tracks, job.total_discs, cover)
        return job.track.id, status, None
    except Exception as exc:
        return job.track.id, FAILED, str(exc)


def _sync_into(source: Path, dest: Path) -> None:
    """Move one file and flush it, so directory entries land in call order."""
    shutil.move(str(source), str(dest))
    fd = os.open(dest, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _clear(directory: Path) -> None:
    """Drop the files this tool wrote. Subdirectories are left alone so a build
    does not destroy the calibration ladder or anything the user parked here."""
    for entry in directory.iterdir():
        if entry.is_file():
            entry.unlink()


def build(conn, output_dir: Path = OUTPUT_DIR, covers: dict[int, Path] | None = None,
          workers: int | None = None, on_progress=None, on_log=None) -> BuildResult:
    """Transcode in parallel, then write into output_dir strictly in sort order."""
    audio.ensure_tools()
    output_dir.mkdir(parents=True, exist_ok=True)

    if covers is None:
        settings = profile.load()
        covers = stored_covers(conn) if settings.cover_enabled else {}
    tracks = catalog.buildable_tracks(conn)
    result = BuildResult()
    if not tracks:
        return result

    _clear(output_dir)

    releases = {r.id: r for r in catalog.releases(conn)}
    result.skipped_releases = [
        f"{r.artist} - {r.title}" for r in releases.values() if r.needs_review
    ]
    totals: dict[tuple[int, int], int] = {}
    discs: dict[int, int] = {}
    for track in tracks:
        disc_no = track.disc_no or 1
        totals[(track.release_id, disc_no)] = totals.get((track.release_id, disc_no), 0) + 1
        discs[track.release_id] = max(discs.get(track.release_id, 1), disc_no)

    with tempfile.TemporaryDirectory(prefix="m3talist-") as staging:
        stage = Path(staging)
        jobs = [
            _Job(
                track=track,
                release=releases[track.release_id],
                temp_path=stage / f"{track.sort_index:08d}.mp3",
                total_tracks=totals[(track.release_id, track.disc_no or 1)],
                total_discs=discs[track.release_id],
                cover_path=covers.get(track.release_id),
            )
            for track in tracks
        ]

        outcomes: dict[int, tuple[str, str | None]] = {}
        try:
            with ProcessPoolExecutor(max_workers=workers) as pool:
                for done, (track_id, status, error) in enumerate(
                    pool.map(_transcode_and_tag, jobs), start=1
                ):
                    outcomes[track_id] = (status, error)
                    if on_progress:
                        on_progress(done, len(jobs))
        except BrokenProcessPool as exc:
            result.errors.append(f"worker pool crashed: {exc}")

        # Sequential by sort_index: the write order is the guarantee.
        for job in jobs:
            status, error = outcomes.get(job.track.id, (FAILED, "worker pool crashed"))
            if status == FAILED or not job.temp_path.exists():
                catalog.set_status(conn, job.track.id, FAILED, error)
                result.failed += 1
                result.errors.append(f"{job.track.source_path.name}: {error}")
                continue
            _sync_into(job.temp_path, output_dir / job.track.output_name)
            catalog.set_status(conn, job.track.id, status)
            result.written += 1
            if on_log:
                on_log(job.track.output_name)

    _sync_dir(output_dir)
    conn.commit()
    return result


def copy_to(device_dir: Path, output_dir: Path = OUTPUT_DIR, on_log=None) -> int:
    """Copy the built collection one file at a time, in name order, flushing each.

    Cheap players read tracks in FAT directory-entry order, which is creation
    order. A parallel or bulk copy reorders those entries and undoes the build.
    """
    device_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for source in sorted(output_dir.glob("*.mp3")):
        dest = device_dir / source.name
        shutil.copyfile(source, dest)
        fd = os.open(dest, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        written += 1
        if on_log:
            on_log(source.name)
    _sync_dir(device_dir)
    return written


def calibrate(dest: Path = CALIBRATE_DIR) -> list[Path]:
    """Write the cover-art ladder: identical audio, escalating artwork risk."""
    audio.ensure_tools()
    dest.mkdir(parents=True, exist_ok=True)
    _clear(dest)

    with tempfile.TemporaryDirectory(prefix="m3talist-cal-") as staging:
        tone = Path(staging) / "tone.mp3"
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
             "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", "-ac", "2", str(tone)],
            check=True,
        )
        ladder = calibration_set()
        written = []
        for position, (label, cover) in enumerate(ladder, start=1):
            target = dest / f"{label}.mp3"
            shutil.copyfile(tone, target)
            track = Track(source_path=target, title=label.upper(), artist="M3TALIST",
                          track_no=position)
            release = Release(artist="M3TALIST", title="COVER CALIBRATION", source_dir=dest)
            tags.write(target, track, release, total_tracks=len(ladder), cover=cover)
            written.append(target)
    return written
