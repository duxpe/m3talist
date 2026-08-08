"""Cover art conversion for the SL6801/SL6806 target device.

The device's ID3 parser is undocumented; see docs/device-sl680x.md ("The one
open question: cover art"). Community heuristics say small baseline
(non-progressive) JPEG is what simple decoders tolerate, so every JPEG this
module writes goes through save(..., progressive=False) explicitly - nothing
here ever inherits progressive-ness from an input file.

Pure functions: no file I/O, no knowledge of MP3s or tags. The pipeline
decides what to do with the bytes returned here.
"""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from m3talist.profile import COVER_LADDER_PX

_JPEG_QUALITY = 85
_BACKGROUND = (20, 20, 20)
_BORDER = (255, 210, 0)
_TEXT = (255, 255, 255)


def _encode(image: Image.Image, *, progressive: bool) -> bytes:
    buffer = BytesIO()
    image.save(
        buffer,
        format="JPEG",
        progressive=progressive,
        optimize=True,
        quality=_JPEG_QUALITY,
    )
    return buffer.getvalue()


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    if image.mode == "RGB":
        return image
    rgba = image.convert("RGBA")
    flattened = Image.new("RGB", rgba.size, "white")
    flattened.paste(rgba, mask=rgba.getchannel("A"))
    return flattened


def to_baseline_jpeg(data: bytes, max_px: int) -> bytes | None:
    """Decode arbitrary image bytes into a baseline JPEG inside a max_px square."""
    try:
        image = Image.open(BytesIO(data))
        image.load()
        rgb_image = _flatten_to_rgb(image)
        rgb_image.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
        return _encode(rgb_image, progressive=False)
    except Exception:
        return None


def _draw_placeholder(size_px: int, label: str) -> Image.Image:
    image = Image.new("RGB", (size_px, size_px), _BACKGROUND)
    draw = ImageDraw.Draw(image)

    border = max(size_px // 20, 2)
    draw.rectangle(
        (border, border, size_px - border - 1, size_px - border - 1),
        outline=_BORDER,
        width=max(border // 2, 1),
    )

    font = ImageFont.load_default()
    draw.multiline_text(
        (border * 2, border * 2),
        f"{label}\n{size_px}px",
        fill=_TEXT,
        font=font,
    )
    return image


def placeholder(size_px: int, label: str) -> bytes:
    """Self-contained baseline JPEG test cover; needs no font file on disk."""
    return _encode(_draw_placeholder(size_px, label), progressive=False)


def calibration_set() -> list[tuple[str, bytes | None]]:
    """The device calibration ladder, ascending risk, one entry per test file.

    The final rung reuses the exact same rendered image as the largest
    baseline rung, saved progressive instead of baseline, so it isolates the
    encoding variable from the size variable.
    """
    entries: list[tuple[str, bytes | None]] = [("00-no-cover", None)]

    largest_image: Image.Image | None = None
    for index, size_px in enumerate(COVER_LADDER_PX, start=1):
        name = f"{index:02d}-{size_px}px"
        largest_image = _draw_placeholder(size_px, name)
        entries.append((name, _encode(largest_image, progressive=False)))

    progressive_index = len(COVER_LADDER_PX) + 1
    largest_px = COVER_LADDER_PX[-1]
    entries.append(
        (
            f"{progressive_index:02d}-{largest_px}px-progressive",
            _encode(largest_image, progressive=True),
        )
    )
    return entries
