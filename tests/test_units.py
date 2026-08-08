from pathlib import Path

import pytest

from m3talist import naming
from m3talist.audio import is_target_ready
from m3talist.models import AudioInfo


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Coração Selvagem", "coracao-selvagem"),
        ("  Money (Remaster)  ", "money-remaster"),
        ("???", "untitled"),
        ("01 Speak to Me", "01-speak-to-me"),
    ],
)
def test_slug(raw, expected):
    assert naming.slug(raw) == expected


@pytest.mark.parametrize(
    "stem,expected",
    [
        ("01 - Speak to Me", 1),
        ("12", 12),
        ("1984 Orwell", None),
        ("2001-a-space-odyssey", None),
    ],
)
def test_track_no_from_filename(stem, expected):
    assert naming.track_no_from_filename(Path(f"{stem}.mp3")) == expected


def test_slug_keeps_leading_digits():
    """The old implementation stripped these, which is what broke album order."""
    assert naming.slug("01 - Speak to Me").startswith("01")


def test_target_ready_tolerates_bitrate_drift_but_not_format_mismatch():
    exact = AudioInfo("mp3", 128_000, 44_100, 2, 1000)
    assert is_target_ready(exact)
    assert is_target_ready(AudioInfo("mp3", 129_000, 44_100, 2, 1000))
    assert not is_target_ready(AudioInfo("mp3", 320_000, 44_100, 2, 1000))
    assert not is_target_ready(AudioInfo("flac", 128_000, 44_100, 2, 1000))
    assert not is_target_ready(AudioInfo("mp3", 128_000, 48_000, 2, 1000))
    assert not is_target_ready(AudioInfo("mp3", 128_000, 44_100, 1, 1000))
    assert not is_target_ready(None)
