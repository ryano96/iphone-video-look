"""Render Snapchat classic caption bar as a transparent PNG overlay.

Tuned for 9:16 video (canonical 1080×1920):
  - Font: Helvetica / Nimbus Sans, 2.75% of frame width
  - Bar: full width, hugs text with tight padding (not the old fixed 74px strip)
  - Bar fill: black @ 60%; centered vertically; grows up/down for extra lines
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Canonical 9:16 reference
REF_W = 1080
REF_H = 1920
FONT_WIDTH_RATIO = 0.0275
V_PAD_RATIO = 0.11  # vertical padding each side, fraction of glyph height
BAR_ALPHA = 0.6
BAR_RGB = (0, 0, 0)
MAX_LINES = 6

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/urw-base35/NimbusSans-Regular.otf",
    "/usr/share/fonts/type1/urw-base35/NimbusSans-Regular.otf",
    "C:/Windows/Fonts/Helvetica.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _font_path() -> str:
    for path in FONT_CANDIDATES:
        if Path(path).is_file():
            return path
    raise RuntimeError("Snap caption font not found.")


def snap_metrics(frame_w: int, frame_h: int) -> dict:
    scale = frame_h / REF_H
    return {
        "font_size": max(11, round(frame_w * FONT_WIDTH_RATIO)),
        "anchor_center_y": frame_h // 2,
        "line_gap": max(1, round(2 * scale)),
        "h_pad": max(6, round(frame_w * 0.025)),
    }


def _glyph_height(font: ImageFont.FreeTypeFont) -> int:
    bbox = font.getbbox("Mg")
    return bbox[3] - bbox[1]


def _text_width(text: str, font: ImageFont.FreeTypeFont) -> int:
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0]


def _wrap_lines(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    *,
    max_lines: int = MAX_LINES,
) -> list[str]:
    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = ""
    word_idx = 0
    while word_idx < len(words):
        word = words[word_idx]
        trial = f"{current} {word}".strip() if current else word
        if _text_width(trial, font) <= max_width:
            current = trial
            word_idx += 1
            continue

        if current:
            lines.append(current)
            current = ""
            if len(lines) >= max_lines:
                remainder = " ".join(words[word_idx:])
                lines[-1] = _truncate_to_width(remainder, font, max_width)
                return lines
            continue

        lines.append(_truncate_to_width(word, font, max_width))
        word_idx += 1
        if len(lines) >= max_lines:
            return lines

    if current:
        lines.append(current)
    return lines[:max_lines]


def _truncate_to_width(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    if _text_width(text, font) <= max_width:
        return text
    trimmed = text
    while trimmed and _text_width(trimmed + "…", font) > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + "…") if trimmed else "…"


def _bar_height(glyph_h: int, line_count: int, line_gap: int) -> int:
    v_pad = max(4, round(glyph_h * V_PAD_RATIO))
    if line_count <= 1:
        return glyph_h + 2 * v_pad
    text_block = glyph_h * line_count + line_gap * (line_count - 1)
    return text_block + 2 * v_pad


def render_overlay_png(caption: str, frame_w: int, frame_h: int, out_path: Path) -> None:
    caption = " ".join(caption.strip().split())
    if not caption:
        raise ValueError("Empty caption")
    if frame_w < 1 or frame_h < 1:
        raise ValueError("Invalid frame size")

    m = snap_metrics(frame_w, frame_h)
    font = ImageFont.truetype(_font_path(), m["font_size"])
    lines = _wrap_lines(caption, font, frame_w - 2 * m["h_pad"])
    if not lines:
        raise ValueError("Caption could not be rendered")

    glyph_h = _glyph_height(font)
    line_step = glyph_h + m["line_gap"]
    bar_h = min(_bar_height(glyph_h, len(lines), m["line_gap"]), frame_h)
    bar_y = m["anchor_center_y"] - bar_h // 2
    bar_y = max(0, min(bar_y, frame_h - bar_h))

    overlay = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    bar = Image.new("RGBA", (frame_w, bar_h), (*BAR_RGB, int(255 * BAR_ALPHA)))
    draw = ImageDraw.Draw(bar)

    block_h = glyph_h if len(lines) == 1 else line_step * len(lines) - m["line_gap"]
    y = (bar_h - block_h) // 2
    for line in lines:
        bbox = font.getbbox(line)
        text_w = bbox[2] - bbox[0]
        x = max(0, (frame_w - text_w) // 2)
        draw.text((x, y - bbox[1]), line, font=font, fill=(255, 255, 255, 255))
        y += line_step

    overlay.paste(bar, (0, bar_y), bar)
    overlay.save(out_path, "PNG")