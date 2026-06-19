"""FFmpeg pipeline: iPhone look + optional Snapchat caption overlay."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from snap_caption import render_overlay_png

MAX_BYTES = 100 * 1024 * 1024
MAX_DURATION_SEC = 120
MAX_CAPTION_LEN = 220


def _run(cmd: list[str], *, timeout: int = 900) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "ffmpeg failed").strip()
        lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
        for ln in reversed(lines):
            if any(k in ln.lower() for k in ("error", "invalid", "failed")):
                raise RuntimeError(ln[:600])
        raise RuntimeError(err[-1200:])


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


def _scaled_size(width: int, height: int) -> tuple[int, int]:
    if width <= 0 or height <= 0:
        return 720, 1280
    sw = min(1280, width)
    sh = int(round(sw * height / width))
    sh = max(2, sh - (sh % 2))
    return sw, sh


def _iphone_filter() -> str:
    return (
        "fps=30,"
        "scale='min(1280,iw)':-2:flags=fast_bilinear,"
        "scale='trunc(iw/2)*2':'trunc(ih/2)*2',"
        "eq=contrast=1.06:brightness=0.02:saturation=1.1:gamma=0.97,"
        "colortemperature=7200,"
        "noise=alls=5:allf=t,"
        "format=yuv420p"
    )


def process_to_iphone_look(
    src: Path,
    dst: Path,
    *,
    caption: str = "",
    work_dir: Path | None = None,
) -> dict:
    info = probe_video(src)
    if info["duration"] > MAX_DURATION_SEC:
        raise RuntimeError(f"Video too long (max {MAX_DURATION_SEC // 60} min).")
    if src.stat().st_size > MAX_BYTES:
        raise RuntimeError(f"File too large (max {MAX_BYTES // (1024 * 1024)} MB).")

    caption = (caption or "").strip()
    if len(caption) > MAX_CAPTION_LEN:
        raise RuntimeError(f"Caption too long (max {MAX_CAPTION_LEN} characters).")

    tmp = work_dir or src.parent
    has_audio = _has_audio(src)

    if caption:
        temp_vid = tmp / "iphone_pass.mp4"
        overlay_png = tmp / "snap_caption.png"

        cmd_pass = [
            "ffmpeg", "-y", "-threads", "1", "-i", str(src),
            "-vf", _iphone_filter(),
            "-c:v", "libx264", "-profile:v", "main", "-level", "3.1",
            "-pix_fmt", "yuv420p", "-crf", "28",
            "-maxrate", "4M", "-bufsize", "8M",
            "-preset", "ultrafast",
        ]
        if has_audio:
            cmd_pass += ["-c:a", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "2"]
        else:
            cmd_pass += ["-an"]
        cmd_pass.append(str(temp_vid))
        _run(cmd_pass, timeout=max(180, int(info["duration"] * 6) + 90))

        scaled = probe_video(temp_vid)
        render_overlay_png(
            caption,
            scaled["width"],
            scaled["height"],
            overlay_png,
        )

        cmd_overlay = [
            "ffmpeg", "-y", "-threads", "1",
            "-i", str(temp_vid),
            "-i", str(overlay_png),
            "-filter_complex",
            "[1:v][0:v]scale2ref[cap][base];[base][cap]overlay=0:0:format=auto,format=yuv420p",
            "-c:v", "libx264", "-profile:v", "main", "-crf", "28",
            "-preset", "ultrafast", "-movflags", "+faststart",
            "-metadata", "com.apple.quicktime.make=Apple",
            "-metadata", "com.apple.quicktime.model=iPhone 15",
        ]
        if has_audio:
            cmd_overlay += ["-c:a", "copy"]
        else:
            cmd_overlay += ["-an"]
        cmd_overlay.append(str(dst))
        _run(cmd_overlay, timeout=max(120, int(info["duration"] * 4) + 60))
        temp_vid.unlink(missing_ok=True)
        overlay_png.unlink(missing_ok=True)
    else:
        cmd = [
            "ffmpeg", "-y", "-threads", "1", "-i", str(src),
            "-vf", _iphone_filter(),
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
        scaled = probe_video(dst)

    return {
        "input": info,
        "size_bytes": dst.stat().st_size,
        "caption": bool(caption),
        "frame": {"w": scaled["width"], "h": scaled["height"]},
    }


def _has_audio(path: Path) -> bool:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return bool(proc.stdout.strip())