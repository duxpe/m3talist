import re
import unicodedata
from pathlib import Path

from m3talist.models import Track

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_LEADING_TRACK_NO = re.compile(r"^(\d+)(?:[ .\-_]|$)")


def slug(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    without_marks = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    ascii_text = without_marks.encode("ascii", "ignore").decode("ascii").lower()
    hyphenated = _NON_ALNUM.sub("-", ascii_text).strip("-")
    return hyphenated or "untitled"


def track_no_from_filename(path: Path) -> int | None:
    match = _LEADING_TRACK_NO.match(path.stem)
    if not match:
        return None
    number = int(match.group(1))
    return number if number <= 999 else None


def output_name(sort_index: int, track: Track, width: int = 4) -> str:
    title = track.title or track.source_path.stem
    return f"{sort_index:0{width}d}-{slug(title)}.mp3"
