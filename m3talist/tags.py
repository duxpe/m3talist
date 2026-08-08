"""ID3 read/write for the device-safe output format.

Target format is fixed in profile.py: ID3v2.3 with an ID3v1 tail, UTF-16 text
with BOM, TYER instead of v2.4's TDRC. See docs/m3talist-v2.md and
docs/device-sl680x.md for why.

FRAMES is the single source of truth for field name <-> frame id, replacing
the old module's separate lookup chain and construction chain.
"""

from pathlib import Path

from mutagen.id3 import ID3, ID3NoHeaderError, APIC, TALB, TCON, TIT2, TPE1, TPE2, TPOS, TRCK, TYER

from m3talist.models import Release, Track
from m3talist.profile import ID3_TEXT_ENCODING, ID3_VERSION, ID3V1_MODE

FRAMES: dict[str, str] = {
    "title": "TIT2",
    "artist": "TPE1",
    "album_artist": "TPE2",
    "album": "TALB",
    "track_no": "TRCK",
    "disc_no": "TPOS",
    "year": "TYER",
    "genre": "TCON",
}

_FRAME_CLASSES: dict[str, type] = {
    "TIT2": TIT2,
    "TPE1": TPE1,
    "TPE2": TPE2,
    "TALB": TALB,
    "TRCK": TRCK,
    "TPOS": TPOS,
    "TYER": TYER,
    "TCON": TCON,
}

_INT_FIELDS = {"track_no", "disc_no", "year"}


def _load(path: Path) -> ID3:
    # v2_version must be passed on load, not just on save: mutagen defaults
    # to translating loaded frames to v2.4 (TYER -> TDRC) unless told
    # otherwise, which would silently defeat "never write TDRC".
    return ID3(path, v2_version=ID3_VERSION)


def _as_int(text: str) -> int | None:
    try:
        return int(text.split("/", 1)[0])
    except ValueError:
        return None


def read(path: Path) -> dict:
    """Best-effort tag read for the scan. Never raises."""
    values: dict = dict.fromkeys(FRAMES)
    try:
        tags = _load(path)
    except Exception:
        return values

    for field, frame_id in FRAMES.items():
        frame = tags.get(frame_id)
        if frame is None or not frame.text:
            continue
        text = str(frame.text[0])
        values[field] = _as_int(text) if field in _INT_FIELDS else (text or None)
    return values


def _set_text_frame(tags: ID3, frame_id: str, value: str | None) -> None:
    tags.delall(frame_id)
    if value is not None:
        tags.add(_FRAME_CLASSES[frame_id](encoding=ID3_TEXT_ENCODING, text=[value]))


def _track_number(track: Track, total_tracks: int | None) -> str | None:
    if track.track_no is None:
        return None
    if total_tracks is not None:
        return f"{track.track_no}/{total_tracks}"
    return str(track.track_no)


def _disc_number(track: Track, total_discs: int | None) -> str | None:
    if total_discs is None or total_discs <= 1 or track.disc_no is None:
        return None
    return str(track.disc_no)


def write(
    path: Path,
    track: Track,
    release: Release,
    total_tracks: int | None = None,
    total_discs: int | None = None,
    cover: bytes | None = None,
) -> None:
    """Write the device-safe tag set. Rewrites only the frames it manages."""
    try:
        tags = _load(path)
    except ID3NoHeaderError:
        tags = ID3()

    # Per-track fields come from the track; album-wide fields come from the
    # release, which holds the confirmed value shared by every track in it.
    values = {
        "TIT2": track.title,
        "TPE1": track.artist,
        "TCON": track.genre,
        "TPE2": release.artist,
        "TALB": release.title,
        "TYER": None if release.year is None else str(release.year),
        "TRCK": _track_number(track, total_tracks),
        "TPOS": _disc_number(track, total_discs),
    }
    for frame_id, value in values.items():
        _set_text_frame(tags, frame_id, value)

    tags.delall("APIC")
    if cover is not None:
        tags.add(APIC(encoding=ID3_TEXT_ENCODING, mime="image/jpeg", type=3, desc="", data=cover))

    tags.save(path, v1=ID3V1_MODE, v2_version=ID3_VERSION)
