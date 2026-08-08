"""Audio probing and transcoding via ffmpeg/ffprobe.

Replaces pydub, which is unmaintained and broken on Python 3.13+ (the stdlib
`audioop` module it depends on was removed). ffmpeg and ffprobe are invoked
directly through subprocess instead.
"""

import json
import shutil
import subprocess
from pathlib import Path

from mutagen.mp3 import MP3, BitrateMode

from m3talist.models import AudioInfo, COPIED, TRANSCODED
from m3talist.profile import TARGET_BITRATE, TARGET_CHANNELS, TARGET_CODEC, TARGET_SAMPLE_RATE

BITRATE_TOLERANCE = 0.02


class ToolMissing(RuntimeError):
    pass


def ensure_tools() -> None:
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if not missing:
        return
    raise ToolMissing(
        f"Missing required tool(s): {', '.join(missing)}. "
        "ffmpeg provides both. Run `make deps` to install it for this platform, "
        "or `make doctor` to see the exact command."
    )


def probe(path: Path) -> AudioInfo | None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
        stream = next(s for s in data["streams"] if s.get("codec_type") == "audio")
        fmt = data.get("format", {})
        bit_rate = int(stream.get("bit_rate", fmt.get("bit_rate", 0)))
        return AudioInfo(
            codec=stream["codec_name"],
            bitrate=bit_rate,
            sample_rate=int(stream["sample_rate"]),
            channels=int(stream["channels"]),
            duration_ms=int(float(fmt["duration"]) * 1000),
        )
    except Exception:
        return None


def is_target_ready(info: AudioInfo | None) -> bool:
    if info is None:
        return False
    if info.codec != TARGET_CODEC:
        return False
    if info.sample_rate != TARGET_SAMPLE_RATE:
        return False
    if info.channels != TARGET_CHANNELS:
        return False
    return abs(info.bitrate - TARGET_BITRATE) <= TARGET_BITRATE * BITRATE_TOLERANCE


def _is_cbr(path: Path) -> bool:
    """ffprobe's bit_rate is an average, so a VBR file can land inside the CBR
    tolerance window. Only mutagen's bitrate_mode proves the encoding is fixed."""
    try:
        return MP3(path).info.bitrate_mode == BitrateMode.CBR
    except Exception:
        return False


def _last_meaningful_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def prepare(source: Path, dest: Path, info: AudioInfo | None = None) -> str:
    if info is None:
        info = probe(source)
    if is_target_ready(info) and _is_cbr(source):
        shutil.copyfile(source, dest)
        return COPIED
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-y",
            "-i", str(source),
            "-map", "0:a:0",
            "-c:a", "libmp3lame",
            "-b:a", "128k",
            "-ar", "44100",
            "-ac", "2",
            "-map_metadata", "-1",
            str(dest),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = _last_meaningful_line(result.stderr) or f"ffmpeg exited with {result.returncode}"
        raise RuntimeError(f"ffmpeg failed on {source.name}: {detail}")
    return TRANSCODED
