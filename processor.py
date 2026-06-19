"""FFmpeg pipeline: make AI footage look like casual iPhone video."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

MAX_BYTES = 200 * 1024 * 1024  # 200 MB upload cap
MAX_DURATION_SEC = 180  # 3 minutes


def _run(cmd: list[str], *, timeout: int = 600) -> None:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "ffmpeg failed").strip()
        raise RuntimeError(err[-2000:])


def probe_video(path: Path) -> dict:
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(path),
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
    duration = float(data.get("format", {}).get("duration") or 0)
    return {
        "duration": duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": video.get("r_frame_rate", "30/1"),
    }


def _iphone_video_filter() -> str:
    # Casual iPhone look: 30fps cadence, warm grade, mild sharpen, light grain,
    # tiny handheld wobble, capped 1080p, phone-like contrast curve.
    return (
        "fps=30,"
        "scale='min(1920,iw)':'min(1920,ih)':force_original_aspect_ratio=decrease:flags=lanczos,"
        "scale='trunc(iw/2)*2':'trunc(ih/2)*2',"
        "eq=contrast=1.05:brightness=0.02:saturation=1.08:gamma=0.98,"
        "curves=r='0/0.02 0.5/0.52 1/0.98':"
        "g='0/0.01 0.5/0.5 1/0.96':"
        "b='0/0.03 0.5/0.48 1/0.94',"
        "colortemperature=7000,"
        "unsharp=5:5:0.35:5:5:0.0,"
        "noise=alls=7:allf=t+u,"
        "crop=w='iw-6':h='ih-6':x='3+1.2*sin(2*PI*t*0.35)':y='3+1.0*cos(2*PI*t*0.27)',"
        "scale=iw+6:ih+6,"
        "format=yuv420p"
    )


def process_to_iphone_look(src: Path, dst: Path) -> dict:
    info = probe_video(src)
    if info["duration"] > MAX_DURATION_SEC:
        raise RuntimeError(f"Video too long (max {MAX_DURATION_SEC // 60} min).")
    if src.stat().st_size > MAX_BYTES:
        raise RuntimeError(f"File too large (max {MAX_BYTES // (1024 * 1024)} MB).")

    vf = _iphone_video_filter()
    has_audio = _has_audio(src)

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-profile:v",
        "high",
        "-level",
        "4.0",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "27",
        "-maxrate",
        "6M",
        "-bufsize",
        "12M",
        "-preset",
        "medium",
        "-movflags",
        "+faststart",
        "-metadata",
        "com.apple.quicktime.make=Apple",
        "-metadata",
        "com.apple.quicktime.model=iPhone 15",
    ]

    if has_audio:
        cmd += [
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-ac",
            "2",
        ]
    else:
        cmd += ["-an"]

    cmd.append(str(dst))
    _run(cmd, timeout=max(120, int(info["duration"] * 4) + 60))

    out_info = probe_video(dst)
    return {
        "input": info,
        "output": out_info,
        "size_bytes": dst.stat().st_size,
    }


def _has_audio(path: Path) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return bool(proc.stdout.strip())


def process_upload(data: bytes, filename: str) -> tuple[Path, dict, tempfile.TemporaryDirectory]:
    """Write upload to temp dir, process, return output path + meta + temp dir handle."""
    if len(data) > MAX_BYTES:
        raise RuntimeError(f"File too large (max {MAX_BYTES // (1024 * 1024)} MB).")

    tmp = tempfile.TemporaryDirectory(prefix="iphonevid_")
    root = Path(tmp.name)
    ext = Path(filename or "video.mp4").suffix.lower() or ".mp4"
    if ext not in {".mp4", ".mov", ".webm", ".mkv", ".m4v"}:
        ext = ".mp4"

    src = root / f"input{ext}"
    dst = root / "output.mp4"
    src.write_bytes(data)

    meta = process_to_iphone_look(src, dst)
    return dst, meta, tmp