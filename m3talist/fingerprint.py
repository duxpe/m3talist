"""Duplicate detection, in two tiers.

Tier one hashes the decoded audio with ffmpeg, which is already required. Tags
are not part of the decoded stream, so the same file copied into a second album
and retagged still matches. This works on any file of any length.

Tier two is Chromaprint (`fpcalc`), an optional binary that matches the same
recording across different encodings. It needs at least ~3 seconds of audio and
returns nothing for anything shorter.

Neither tier ever raises: a file that cannot be hashed or fingerprinted is
reported as skipped and the run continues.
"""

import json
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from m3talist import catalog
from m3talist.models import Track

TIMEOUT_SECONDS = 30
MIN_FINGERPRINT_SECONDS = 3


@dataclass
class ScanReport:
    hashed: int = 0
    fingerprinted: int = 0
    too_short: int = 0
    fingerprint_failed: int = 0
    unreadable: list[str] = field(default_factory=list)

    @property
    def fpcalc_available(self) -> bool:
        return available()


def available() -> bool:
    return shutil.which("fpcalc") is not None


def content_hash(path: Path) -> str | None:
    """MD5 of the decoded audio stream, ignoring tags entirely."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
             "-map", "0:a:0", "-f", "md5", "-"],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=True,
        )
        digest = result.stdout.strip()
        return digest.removeprefix("MD5=") if digest.startswith("MD5=") else None
    except Exception:
        return None


def compute(path: Path) -> str | None:
    if not available():
        return None
    try:
        result = subprocess.run(
            ["fpcalc", "-json", str(path)],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS, check=True,
        )
        return json.loads(result.stdout)["fingerprint"] or None
    except Exception:
        return None


def scan(
    conn: sqlite3.Connection,
    tracks: list[Track],
    on_progress: Callable[[int, int], None] | None = None,
) -> ScanReport:
    report = ScanReport()
    total = len(tracks)

    for done, track in enumerate(tracks, start=1):
        if not track.content_hash:
            digest = content_hash(track.source_path)
            if digest:
                catalog.set_content_hash(conn, track.id, digest)
                track.content_hash = digest
                report.hashed += 1
            else:
                report.unreadable.append(track.source_path.name)

        if available() and not track.fingerprint:
            duration = track.audio.duration_ms if track.audio else None
            if duration is not None and duration < MIN_FINGERPRINT_SECONDS * 1000:
                report.too_short += 1
            else:
                value = compute(track.source_path)
                if value:
                    catalog.set_fingerprint(conn, track.id, value)
                    track.fingerprint = value
                    report.fingerprinted += 1
                else:
                    # Long enough, yet fpcalc produced nothing: corrupt input,
                    # a crash or a timeout. Not the same story as "too short".
                    report.fingerprint_failed += 1

        if on_progress is not None:
            on_progress(done, total)

    conn.commit()
    return report


def duplicates(conn: sqlite3.Connection) -> list[tuple[str, list[Track]]]:
    return catalog.duplicate_groups(conn)
