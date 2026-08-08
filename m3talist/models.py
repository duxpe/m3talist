from dataclasses import dataclass, field
from pathlib import Path

AUDIO_SUFFIXES = frozenset({".mp3", ".wav", ".m4a", ".flac", ".ogg", ".opus", ".wma"})

PENDING = "pending"
COPIED = "copied"
TRANSCODED = "transcoded"
FAILED = "failed"


@dataclass
class AudioInfo:
    codec: str
    bitrate: int
    sample_rate: int
    channels: int
    duration_ms: int


@dataclass
class Track:
    source_path: Path
    title: str | None = None
    artist: str | None = None
    album_artist: str | None = None
    album: str | None = None
    disc_no: int | None = None
    track_no: int | None = None
    year: int | None = None
    genre: str | None = None
    audio: AudioInfo | None = None
    fingerprint: str | None = None
    content_hash: str | None = None
    mbid: str | None = None
    sort_index: int | None = None
    output_name: str | None = None
    status: str = PENDING
    error: str | None = None
    id: int | None = None
    release_id: int | None = None


@dataclass
class Release:
    artist: str
    title: str
    source_dir: Path
    year: int | None = None
    mbid: str | None = None
    cover_path: Path | None = None
    needs_review: bool = False
    id: int | None = None


@dataclass
class BuildResult:
    written: int = 0
    failed: int = 0
    skipped_releases: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
