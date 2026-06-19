"""Render Snapchat classic caption bar as a transparent PNG overlay.

Measured from classic Snap UI (640×1136 iPhone canvas, Kapwing 720×1280 template):
  - Font: Helvetica Regular, 35px at 1136h (~3.08% of frame height)
  - Bar: edge-to-edge, grows with lines, black @ 60%
  - Anchor: single-line bar center at y=450+37 (~42.9% from top)
  - Lines stack from the middle: bar expands up/down, each line centered
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
MAX_LINES = 6

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
    bar_h_single = max(18, round(REF_BAR_H * scale))
    bar_y = max(0, min(round(REF_BAR_Y * scale), frame_h - 1))
    return {
        "scale": scale,
        "font_size": max(11, round(REF_FONT * scale)),
        "bar_h_single": bar_h_single,
        "bar_y": bar_y,
        "anchor_center_y": bar_y + bar_h_single // 2,
        "h_pad": max(8, round(REF_H_PAD * scale)),
        "v_pad": max(6, round(REF_V_PAD * scale)),
        "line_gap": max(1, round(2 * scale)),
    }


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


def _layout_lines(
    text: str,
    font_path: str,
    font_size: int,
    max_width: int,
    frame_h: int,
    v_pad: int,
    line_gap: int,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    font = ImageFont.truetype(font_path, font_size)
    lines = _wrap_lines(text, font, max_width)
    if not lines:
        return font, []

    line_h = font.size + line_gap
    max_bar_h = int(frame_h * 0.22)
    while len(lines) > 1 and v_pad * 2 + line_h * len(lines) > max_bar_h and font_size > 10:
        font_size -= 1
        font = ImageFont.truetype(font_path, font_size)
        lines = _wrap_lines(text, font, max_width)
        line_h = font.size + line_gap

    return font, lines


def render_overlay_png(caption: str, frame_w: int, frame_h: int, out_path: Path) -> None:
    caption = " ".join(caption.strip().split())
    if not caption:
        raise ValueError("Empty caption")
    if frame_w < 1 or frame_h < 1:
        raise ValueError("Invalid frame size")

    m = snap_metrics(frame_w, frame_h)
    max_text_w = frame_w - 2 * m["h_pad"]

    font, lines = _layout_lines(
        caption,
        _font_path(),
        m["font_size"],
        max_text_w,
        frame_h,
        m["v_pad"],
        m["line_gap"],
    )
    if not lines:
        raise ValueError("Caption could not be rendered")

    line_h = font.size + m["line_gap"]
    bar_h = m["v_pad"] * 2 + line_h * len(lines)
    bar_h = min(bar_h, frame_h)
    bar_y = m["anchor_center_y"] - bar_h // 2
    bar_y = max(0, min(bar_y, frame_h - bar_h))

    overlay = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    bar = Image.new("RGBA", (frame_w, bar_h), (0, 0, 0, int(255 * REF_BAR_ALPHA)))
    draw = ImageDraw.Draw(bar)

    block_h = line_h * len(lines)
    y = (bar_h - block_h) // 2
    for line in lines:
        bbox = font.getbbox(line)
        text_w = bbox[2] - bbox[0]
        x = max(0, (frame_w - text_w) // 2)
        draw.text((x, y - bbox[1]), line, font=font, fill=(255, 255, 255, 255))
        y += line_h

    overlay.paste(bar, (0, bar_y), bar)
    overlay.save(out_path, "PNG")