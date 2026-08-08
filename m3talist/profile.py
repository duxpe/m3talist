"""Output format for the target device.

One device, one format. These are constants rather than configuration because
where the conservative option costs nothing, it wins without an experiment.
See docs/device-sl680x.md for what was settled and why.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path

from m3talist.config import CONFIG_FILE

TARGET_CODEC = "mp3"
TARGET_BITRATE = 128_000
TARGET_SAMPLE_RATE = 44_100
TARGET_CHANNELS = 2

ID3_VERSION = 3
ID3_TEXT_ENCODING = 1
ID3V1_MODE = 2

COVER_LADDER_PX = (100, 200, 300, 500)


@dataclass(frozen=True)
class Settings:
    cover_max_px: int | None = None
    offline: bool = False
    user_agent: str = "m3talist/2.0 (https://github.com/duxpe/m3talist)"

    @property
    def cover_enabled(self) -> bool:
        return self.cover_max_px is not None


def load(path: Path = CONFIG_FILE) -> Settings:
    if not path.exists():
        return Settings()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return Settings(
        cover_max_px=data.get("cover_max_px"),
        offline=data.get("offline", False),
        user_agent=data.get("user_agent", Settings.user_agent),
    )


def save(settings: Settings, path: Path = CONFIG_FILE) -> None:
    lines = [f"offline = {str(settings.offline).lower()}"]
    if settings.cover_max_px is not None:
        lines.append(f"cover_max_px = {settings.cover_max_px}")
    lines.append(f'user_agent = "{settings.user_agent}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
