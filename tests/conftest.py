import subprocess
from pathlib import Path

import pytest
from mutagen.id3 import ID3, TALB, TIT2, TPE1, TRCK

from m3talist import catalog


def _tone(path: Path, seconds: float = 1.0, frequency: int = 440) -> None:
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"sine=frequency={frequency}:duration={seconds}",
         "-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", "-ac", "2", str(path)],
        check=True,
    )


def _tag(path: Path, title: str, artist: str, album: str, track_no: int | None) -> None:
    tags = ID3()
    tags.add(TIT2(encoding=1, text=[title]))
    tags.add(TPE1(encoding=1, text=[artist]))
    tags.add(TALB(encoding=1, text=[album]))
    if track_no is not None:
        tags.add(TRCK(encoding=1, text=[str(track_no)]))
    tags.save(path, v2_version=3)


@pytest.fixture(scope="session")
def library(tmp_path_factory) -> Path:
    """Three albums covering the tagged, filename-only and unorderable cases.

    Every track gets a distinct frequency. Reusing one would make unrelated
    files byte-identical after decoding and show up as real duplicates.
    """
    root = tmp_path_factory.mktemp("input")
    frequency = iter(range(220, 2000, 37))

    tagged = root / "Pink Floyd - The Dark Side of the Moon"
    tagged.mkdir()
    for position, title in enumerate(["Speak to Me", "Breathe", "Time", "Eclipse"], start=1):
        # Filenames deliberately carry no order information.
        path = tagged / f"{title.lower().replace(' ', '_')}.mp3"
        _tone(path, frequency=next(frequency))
        _tag(path, title, "Pink Floyd", "The Dark Side of the Moon", position)

    numbered = root / "Kraftwerk - Autobahn"
    numbered.mkdir()
    for position, title in enumerate(["Autobahn", "Kometenmelodie", "Mitternacht"], start=1):
        # No TRCK at all: order must come from the filename prefix.
        path = numbered / f"{position:02d} - {title}.mp3"
        _tone(path, frequency=next(frequency))
        _tag(path, title, "Kraftwerk", "Autobahn", None)

    unordered = root / "Various - Mixtape"
    unordered.mkdir()
    for title in ["alpha", "bravo", "charlie"]:
        # Neither TRCK nor a numeric prefix: unorderable on purpose.
        path = unordered / f"{title}.mp3"
        _tone(path, frequency=next(frequency))
        _tag(path, title.upper(), "Various", "Mixtape", None)

    return root


@pytest.fixture
def make_mp3(tmp_path):
    """Build one tagged MP3 on demand, for tests that need a specific shape."""

    def factory(name: str, title: str = "Title", artist: str = "Artist",
                album: str = "Album", track_no: int | None = 1) -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        _tone(path, seconds=0.5)
        _tag(path, title, artist, album, track_no)
        return path

    return factory


@pytest.fixture
def conn(tmp_path):
    connection = catalog.connect(tmp_path / "catalog.db")
    yield connection
    connection.close()
