import sqlite3
from pathlib import Path

from m3talist.config import DB_FILE, WORK_DIR
from m3talist.models import AudioInfo, Release, Track

SCHEMA = """
CREATE TABLE IF NOT EXISTS release (
  id INTEGER PRIMARY KEY,
  artist TEXT NOT NULL,
  title TEXT NOT NULL,
  source_dir TEXT NOT NULL UNIQUE,
  year INTEGER,
  mbid TEXT,
  cover_path TEXT,
  needs_review INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS track (
  id INTEGER PRIMARY KEY,
  release_id INTEGER NOT NULL REFERENCES release(id) ON DELETE CASCADE,
  source_path TEXT NOT NULL UNIQUE,
  output_name TEXT,
  title TEXT,
  artist TEXT,
  album_artist TEXT,
  album TEXT,
  disc_no INTEGER,
  track_no INTEGER,
  year INTEGER,
  genre TEXT,
  duration_ms INTEGER,
  source_codec TEXT,
  source_bitrate INTEGER,
  source_sample_rate INTEGER,
  source_channels INTEGER,
  fingerprint TEXT,
  mbid TEXT,
  sort_index INTEGER,
  status TEXT NOT NULL DEFAULT 'pending',
  error TEXT,
  source_mtime INTEGER,
  source_size INTEGER,
  content_hash TEXT
);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mb_cache (
  query_hash TEXT PRIMARY KEY,
  response TEXT NOT NULL,
  fetched_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS track_release ON track(release_id);
CREATE INDEX IF NOT EXISTS track_sort ON track(sort_index);
CREATE INDEX IF NOT EXISTS track_fingerprint ON track(fingerprint);
CREATE INDEX IF NOT EXISTS track_content_hash ON track(content_hash);
"""


def connect(db_path: Path = DB_FILE) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI may hand one request's dependency, endpoint and teardown to
    # different threadpool workers. Every caller gets its own connection, so
    # relaxing the thread check shares nothing.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _add_missing_columns(conn)
    return conn


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS cannot widen a table an older run created."""
    present = {row["name"] for row in conn.execute("PRAGMA table_info(track)")}
    for column, definition in (
        ("source_mtime", "INTEGER"),
        ("source_size", "INTEGER"),
        ("content_hash", "TEXT"),
    ):
        if column not in present:
            conn.execute(f"ALTER TABLE track ADD COLUMN {column} {definition}")
    conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """INSERT INTO meta (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (key, value),
    )
    conn.commit()


def reset(conn: sqlite3.Connection) -> None:
    """Drop catalogued releases and tracks. The API cache survives."""
    conn.execute("DELETE FROM track")
    conn.execute("DELETE FROM release")
    conn.commit()


def _to_release(row: sqlite3.Row) -> Release:
    return Release(
        id=row["id"],
        artist=row["artist"],
        title=row["title"],
        source_dir=Path(row["source_dir"]),
        year=row["year"],
        mbid=row["mbid"],
        cover_path=Path(row["cover_path"]) if row["cover_path"] else None,
        needs_review=bool(row["needs_review"]),
    )


def _to_track(row: sqlite3.Row) -> Track:
    audio = None
    if row["source_codec"]:
        audio = AudioInfo(
            codec=row["source_codec"],
            bitrate=row["source_bitrate"] or 0,
            sample_rate=row["source_sample_rate"] or 0,
            channels=row["source_channels"] or 0,
            duration_ms=row["duration_ms"] or 0,
        )
    return Track(
        id=row["id"],
        release_id=row["release_id"],
        source_path=Path(row["source_path"]),
        output_name=row["output_name"],
        title=row["title"],
        artist=row["artist"],
        album_artist=row["album_artist"],
        album=row["album"],
        disc_no=row["disc_no"],
        track_no=row["track_no"],
        year=row["year"],
        genre=row["genre"],
        audio=audio,
        fingerprint=row["fingerprint"],
        content_hash=row["content_hash"],
        mbid=row["mbid"],
        sort_index=row["sort_index"],
        status=row["status"],
        error=row["error"],
    )


def add_release(conn: sqlite3.Connection, release: Release) -> int:
    cursor = conn.execute(
        """INSERT INTO release (artist, title, source_dir, year, mbid, cover_path,
                                needs_review)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(source_dir) DO UPDATE SET
             artist=excluded.artist, title=excluded.title,
             year=COALESCE(excluded.year, release.year)
           RETURNING id""",
        (
            release.artist,
            release.title,
            str(release.source_dir),
            release.year,
            release.mbid,
            str(release.cover_path) if release.cover_path else None,
            int(release.needs_review),
        ),
    )
    release.id = cursor.fetchone()["id"]
    return release.id


def add_track(conn: sqlite3.Connection, track: Track, release_id: int) -> int:
    audio = track.audio
    try:
        stat = track.source_path.stat()
        mtime, size = stat.st_mtime_ns, stat.st_size
    except OSError:
        mtime = size = None
    cursor = conn.execute(
        """INSERT INTO track (release_id, source_path, output_name, title, artist,
                              album_artist, album, disc_no, track_no, year, genre,
                              duration_ms, source_codec, source_bitrate,
                              source_sample_rate, source_channels, fingerprint,
                              mbid, sort_index, status, source_mtime, source_size)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(source_path) DO UPDATE SET
             release_id=excluded.release_id, title=excluded.title,
             artist=excluded.artist, album_artist=excluded.album_artist,
             album=excluded.album, disc_no=excluded.disc_no,
             year=COALESCE(excluded.year, track.year),
             genre=COALESCE(excluded.genre, track.genre),
             status=excluded.status,
             -- A manual order lives in track_no. Only a real tag may replace it.
             track_no=COALESCE(excluded.track_no, track.track_no),
             -- The file owns everything derived from its bytes. Leaving these
             -- stale lets a re-encoded track skip the transcode it now needs.
             duration_ms=excluded.duration_ms,
             source_codec=excluded.source_codec,
             source_bitrate=excluded.source_bitrate,
             source_sample_rate=excluded.source_sample_rate,
             source_channels=excluded.source_channels,
             source_mtime=excluded.source_mtime,
             source_size=excluded.source_size,
             -- Rewritten bytes invalidate anything derived from the old ones.
             fingerprint=CASE
               WHEN excluded.source_mtime IS track.source_mtime
                AND excluded.source_size IS track.source_size
               THEN track.fingerprint ELSE NULL END,
             content_hash=CASE
               WHEN excluded.source_mtime IS track.source_mtime
                AND excluded.source_size IS track.source_size
               THEN track.content_hash ELSE NULL END
           RETURNING id""",
        (
            release_id,
            str(track.source_path),
            track.output_name,
            track.title,
            track.artist,
            track.album_artist,
            track.album,
            track.disc_no,
            track.track_no,
            track.year,
            track.genre,
            audio.duration_ms if audio else None,
            audio.codec if audio else None,
            audio.bitrate if audio else None,
            audio.sample_rate if audio else None,
            audio.channels if audio else None,
            track.fingerprint,
            track.mbid,
            track.sort_index,
            track.status,
            mtime,
            size,
        ),
    )
    track.id = cursor.fetchone()["id"]
    track.release_id = release_id
    return track.id


def releases(conn: sqlite3.Connection) -> list[Release]:
    rows = conn.execute("SELECT * FROM release ORDER BY artist, year, title").fetchall()
    return [_to_release(row) for row in rows]


def release(conn: sqlite3.Connection, release_id: int) -> Release | None:
    row = conn.execute("SELECT * FROM release WHERE id = ?", (release_id,)).fetchone()
    return _to_release(row) if row else None


def tracks_of(conn: sqlite3.Connection, release_id: int) -> list[Track]:
    rows = conn.execute(
        """SELECT * FROM track WHERE release_id = ?
           ORDER BY disc_no IS NULL, disc_no, track_no IS NULL, track_no, source_path""",
        (release_id,),
    ).fetchall()
    return [_to_track(row) for row in rows]


def buildable_tracks(conn: sqlite3.Connection) -> list[Track]:
    """Tracks with an assigned order, in the exact sequence they must be written."""
    rows = conn.execute(
        """SELECT t.* FROM track t
           JOIN release r ON r.id = t.release_id
           WHERE t.sort_index IS NOT NULL AND r.needs_review = 0
           ORDER BY t.sort_index"""
    ).fetchall()
    return [_to_track(row) for row in rows]


def set_order(conn: sqlite3.Connection, track_id: int, sort_index: int, output_name: str) -> None:
    conn.execute(
        "UPDATE track SET sort_index = ?, output_name = ? WHERE id = ?",
        (sort_index, output_name, track_id),
    )


def set_track_no(conn: sqlite3.Connection, track_id: int, track_no: int,
                 release_id: int | None = None) -> int:
    """Returns rows changed, so a caller can reject ids from another release."""
    if release_id is None:
        cursor = conn.execute(
            "UPDATE track SET track_no = ? WHERE id = ?", (track_no, track_id)
        )
    else:
        cursor = conn.execute(
            "UPDATE track SET track_no = ? WHERE id = ? AND release_id = ?",
            (track_no, track_id, release_id),
        )
    return cursor.rowcount


def set_release_mbid(conn: sqlite3.Connection, release_id: int, mbid: str | None,
                     year: int | None) -> None:
    conn.execute(
        "UPDATE release SET mbid = ?, year = COALESCE(year, ?) WHERE id = ?",
        (mbid, year, release_id),
    )


def set_release_cover(conn: sqlite3.Connection, release_id: int, cover_path: Path) -> None:
    conn.execute(
        "UPDATE release SET cover_path = ? WHERE id = ?", (str(cover_path), release_id)
    )


def fill_missing_genre(conn: sqlite3.Connection, release_id: int, genre: str) -> None:
    conn.execute(
        "UPDATE track SET genre = COALESCE(genre, ?) WHERE release_id = ?",
        (genre, release_id),
    )


def counts(conn: sqlite3.Connection) -> tuple[int, int]:
    """(tracks, releases awaiting a manual order)."""
    row = conn.execute(
        """SELECT (SELECT COUNT(*) FROM track) AS tracks,
                  (SELECT COUNT(*) FROM release WHERE needs_review = 1) AS review"""
    ).fetchone()
    return row["tracks"], row["review"]


def track_counts(conn: sqlite3.Connection) -> dict[int, int]:
    rows = conn.execute(
        "SELECT release_id, COUNT(*) AS total FROM track GROUP BY release_id"
    ).fetchall()
    return {row["release_id"]: row["total"] for row in rows}


def prune(conn: sqlite3.Connection, seen_paths: set[str]) -> int:
    """Drop tracks whose source file is gone, then releases left with none."""
    existing = conn.execute("SELECT id, source_path FROM track").fetchall()
    stale = [row["id"] for row in existing if row["source_path"] not in seen_paths]
    conn.executemany("DELETE FROM track WHERE id = ?", [(i,) for i in stale])
    conn.execute(
        "DELETE FROM release WHERE id NOT IN (SELECT DISTINCT release_id FROM track)"
    )
    return len(stale)


def all_tracks(conn: sqlite3.Connection) -> list[Track]:
    rows = conn.execute("SELECT * FROM track ORDER BY source_path").fetchall()
    return [_to_track(row) for row in rows]


def set_status(conn: sqlite3.Connection, track_id: int, status: str, error: str | None = None) -> None:
    conn.execute(
        "UPDATE track SET status = ?, error = ? WHERE id = ?", (status, error, track_id)
    )


def set_review(conn: sqlite3.Connection, release_id: int, needs_review: bool) -> None:
    conn.execute(
        "UPDATE release SET needs_review = ? WHERE id = ?", (int(needs_review), release_id)
    )


def set_fingerprint(conn: sqlite3.Connection, track_id: int, fingerprint: str) -> None:
    conn.execute("UPDATE track SET fingerprint = ? WHERE id = ?", (fingerprint, track_id))


def set_content_hash(conn: sqlite3.Connection, track_id: int, content_hash: str) -> None:
    conn.execute("UPDATE track SET content_hash = ? WHERE id = ?", (content_hash, track_id))


DUPLICATE_KINDS = (
    ("content_hash", "identical audio"),
    ("fingerprint", "same recording"),
)


def duplicate_groups(conn: sqlite3.Connection) -> list[tuple[str, list[Track]]]:
    """Duplicates by decoded-audio hash first, then by acoustic fingerprint.

    A hash match means the audio is byte-identical once tags are stripped — the
    same file copied into a second album. A fingerprint match is looser and
    needs fpcalc. Groups already reported by hash are not repeated.
    """
    groups: list[tuple[str, list[Track]]] = []
    reported: set[int] = set()
    for column, kind in DUPLICATE_KINDS:
        rows = conn.execute(
            f"""SELECT * FROM track WHERE {column} IS NOT NULL
                AND {column} IN (
                  SELECT {column} FROM track WHERE {column} IS NOT NULL
                  GROUP BY {column} HAVING COUNT(*) > 1)
                ORDER BY {column}, source_path"""
        ).fetchall()
        buckets: dict[str, list[Track]] = {}
        for row in rows:
            buckets.setdefault(row[column], []).append(_to_track(row))
        for tracks in buckets.values():
            ids = {track.id for track in tracks}
            if ids <= reported:
                continue
            reported |= ids
            groups.append((kind, tracks))
    return groups


def group_by(conn: sqlite3.Connection, column: str) -> list[tuple[str, int]]:
    if column not in {"genre", "year", "artist", "album_artist"}:
        raise ValueError(f"cannot group by {column}")
    rows = conn.execute(
        f"""SELECT COALESCE({column}, 'UNKNOWN') AS label, COUNT(*) AS total
            FROM track GROUP BY label ORDER BY total DESC, label"""
    ).fetchall()
    return [(row["label"], row["total"]) for row in rows]


def cache_get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute(
        "SELECT response FROM mb_cache WHERE query_hash = ?", (key,)
    ).fetchone()
    return row["response"] if row else None


def cache_put(conn: sqlite3.Connection, key: str, response: str) -> None:
    conn.execute(
        """INSERT INTO mb_cache (query_hash, response, fetched_at)
           VALUES (?, ?, datetime('now'))
           ON CONFLICT(query_hash) DO UPDATE SET
             response=excluded.response, fetched_at=excluded.fetched_at""",
        (key, response),
    )
    conn.commit()
