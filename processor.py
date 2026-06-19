"""FFmpeg pipeline: iPhone look + optional Snapchat caption bar."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

MAX_BYTES = 100 * 1024 * 1024
MAX_DURATION_SEC = 120
MAX_CAPTION_LEN = 220
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def _run(cmd: list[str], *, timeout: int = 900) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "ffmpeg failed").strip()
        raise RuntimeError(err[-2000:])


def probe_video(path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError("Could not read video file.")
    data = json.loads(proc.stdout)
    video = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        None,
    )
    if not video:
        raise RuntimeError("No video stream found.")
    return {
        "duration": float(data.get("format", {}).get("duration") or 0),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
    }


def _wrap_caption(text: str, max_chars: int = 34) -> list[str]:
    text = text.strip()
    if not text:
        return []
    lines: list[str] = []
    for paragraph in text.splitlines():
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        current = ""
        for word in paragraph.split():
            trial = f"{current} {word}".strip() if current else word
            if len(trial) <= max_chars:
                current = trial
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines[:6]


def _ffmpeg_path(path: Path) -> str:
    return str(path).replace("\\", "/").replace(":", "\\:")


def _snapchat_caption_filters(caption: str, tmp_dir: Path) -> str:
    """Full-width Snapchat-style gray bar + white bold centered text."""
    lines = _wrap_caption(caption)
    if not lines:
        return ""

    n = len(lines)
    # Bar: edge-to-edge, translucent dark gray (Snapchat-style)
    filters = [
        "drawbox=x=0:y=h*0.58:w=iw"
        f":h=(h*0.038*{n}*1.42+h*0.038*0.95):color=0x2A2A2A@0.72:t=fill",
    ]

    for i, line in enumerate(lines):
        textfile = tmp_dir / f"snap_line_{i}.txt"
        textfile.write_text(line, encoding="utf-8")
        tf = _ffmpeg_path(textfile)
        y = f"h*0.58+h*0.038*0.48+{i}*h*0.038*1.42"
        filters.append(
            f"drawtext=fontfile={FONT_BOLD}:textfile={tf}"
            f":fontcolor=white:fontsize=h*0.038"
            f":x=(w-text_w)/2:y={y}"
        )
    return ",".join(filters)


def _build_video_filter(caption: str, tmp_dir: Path) -> str:
    base = (
        "fps=30,"
        "scale='min(1280,iw)':-2:flags=fast_bilinear,"
        "scale='trunc(iw/2)*2':'trunc(ih/2)*2',"
        "eq=contrast=1.06:brightness=0.02:saturation=1.1:gamma=0.97,"
        "colortemperature=7200,"
        "noise=alls=5:allf=t,"
        "format=yuv420p"
    )
    snap = _snapchat_caption_filters(caption, tmp_dir) if caption.strip() else ""
    return f"{base},{snap}" if snap else base


def process_to_iphone_look(src: Path, dst: Path, *, caption: str = "") -> dict:
    info = probe_video(src)
    if info["duration"] > MAX_DURATION_SEC:
        raise RuntimeError(f"Video too long (max {MAX_DURATION_SEC // 60} min).")
    if src.stat().st_size > MAX_BYTES:
        raise RuntimeError(f"File too large (max {MAX_BYTES // (1024 * 1024)} MB).")

    caption = (caption or "").strip()
    if len(caption) > MAX_CAPTION_LEN:
        raise RuntimeError(f"Caption too long (max {MAX_CAPTION_LEN} characters).")

    tmp_dir = src.parent
    vf = _build_video_filter(caption, tmp_dir)
    has_audio = _has_audio(src)

    cmd = [
        "ffmpeg", "-y", "-threads", "1", "-i", str(src),
        "-vf", vf,
        "-c:v", "libx264", "-profile:v", "main", "-level", "3.1",
        "-pix_fmt", "yuv420p", "-crf", "28",
        "-maxrate", "4M", "-bufsize", "8M",
        "-preset", "ultrafast",
        "-movflags", "+faststart",
        "-metadata", "com.apple.quicktime.make=Apple",
        "-metadata", "com.apple.quicktime.model=iPhone 15",
    ]
    if has_audio:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]
    else:
        cmd += ["-an"]
    cmd.append(str(dst))

    _run(cmd, timeout=max(180, int(info["duration"] * 6) + 90))

    return {"input": info, "size_bytes": dst.stat().st_size, "caption": bool(caption)}


def _has_audio(path: Path) -> bool:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return bool(proc.stdout.strip())