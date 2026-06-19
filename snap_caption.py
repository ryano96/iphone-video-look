"""Render Snapchat classic caption bar as a transparent PNG overlay.

Measured from classic Snap UI (640×1136 iPhone canvas, Kapwing 720×1280 template):
  - Font: Helvetica Regular, 35px at 1136h (~3.08% of frame height)
  - Bar: edge-to-edge, ~74px tall single line (~6.5% of height), black @ 60%
  - Position: y=450 (~39.6% from top), white centered text, regular weight
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Classic snap reference canvas (portrait iPhone snap)
REF_W = 640
REF_H = 1136
REF_FONT = 35
REF_BAR_H = 74
REF_BAR_Y = 450
REF_BAR_ALPHA = 0.6
REF_H_PAD = 16
REF_V_PAD = 12

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "C:/Windows/Fonts/Helvetica.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font_path() -> str:
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return path
    raise RuntimeError("Snap caption font not found.")


def snap_metrics(frame_w: int, frame_h: int) -> dict:
    """Scale classic Snap ratios to the output frame size."""
    scale = frame_h / REF_H
    font_size = max(11, round(REF_FONT * scale))
    return {
        "scale": scale,
        "font_size": font_size,
        "bar_h_single": max(18, round(REF_BAR_H * scale)),
        "bar_y": max(0, min(round(REF_BAR_Y * scale), frame_h - 1)),
        "h_pad": max(8, round(REF_H_PAD * scale)),
        "v_pad": max(6, round(REF_V_PAD * scale)),
        "line_gap": max(1, round(2 * scale)),
        "min_font_size": max(9, round(REF_FONT * scale * 0.78)),
    }


def _text_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def _wrap_lines(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    *,
    max_lines: int = 2,
) -> list[str]:
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = ""
    for word in words:
        trial = f"{current} {word}".strip() if current else word
        if _text_width(trial, font) <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines:
                break
    if current and len(lines) < max_lines:
        lines.append(current)
    return lines[:max_lines]


def _fit_single_line(
    text: str,
    font_path: str,
    font_size: int,
    min_font_size: int,
    max_width: int,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    size = font_size
    while size >= min_font_size:
        font = ImageFont.truetype(font_path, size)
        if _text_width(text, font) <= max_width:
            return font, [text]
        size -= 1
    font = ImageFont.truetype(font_path, min_font_size)
    return font, _wrap_lines(text, font, max_width, max_lines=2)


def render_overlay_png(caption: str, frame_w: int, frame_h: int, out_path: Path) -> None:
    caption = " ".join(caption.strip().split())
    if not caption:
        raise ValueError("Empty caption")
    if frame_w < 1 or frame_h < 1:
        raise ValueError("Invalid frame size")

    m = snap_metrics(frame_w, frame_h)
    font_path = _font_path()
    max_text_w = frame_w - 2 * m["h_pad"]

    font, lines = _fit_single_line(
        caption,
        font_path,
        m["font_size"],
        m["min_font_size"],
        max_text_w,
    )
    if not lines:
        raise ValueError("Caption could not be rendered")

    line_h = font.size + m["line_gap"]
    bar_h = m["v_pad"] * 2 + line_h * len(lines)
    bar_h = min(bar_h, frame_h)
    bar_y = min(m["bar_y"], max(0, frame_h - bar_h))

    overlay = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    bar = Image.new("RGBA", (frame_w, bar_h), (0, 0, 0, int(255 * REF_BAR_ALPHA)))
    draw = ImageDraw.Draw(bar)

    y = m["v_pad"]
    for line in lines:
        bbox = font.getbbox(line)
        text_w = bbox[2] - bbox[0]
        x = max(0, (frame_w - text_w) // 2)
        draw.text((x, y - bbox[1]), line, font=font, fill=(255, 255, 255, 255))
        y += line_h
        if y >= bar_h:
            break

    overlay.paste(bar, (0, bar_y), bar)
    overlay.save(out_path, "PNG")