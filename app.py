"""iPhone Video Look — upload AI video, download phone-style version."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from processor import MAX_BYTES, process_file

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
CHUNK = 1024 * 1024

app = FastAPI(title="iPhone Video Look", version="1.0.0")
_process_lock = asyncio.Lock()

if STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "ffmpeg": shutil.which("ffmpeg") is not None}


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    page = STATIC / "index.html"
    if not page.exists():
        raise HTTPException(500, "UI missing")
    return HTMLResponse(page.read_text(encoding="utf-8"))


async def _save_upload(file: UploadFile, dest: Path) -> None:
    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file.read(CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise HTTPException(
                    400,
                    f"File too large (max {MAX_BYTES // (1024 * 1024)} MB).",
                )
            out.write(chunk)


@app.post("/api/process")
async def process_video(file: UploadFile = File(...)) -> FileResponse:
    if not file.filename:
        raise HTTPException(400, "No file provided")

    async with _process_lock:
        return await _handle_process(file)


async def _handle_process(file: UploadFile) -> FileResponse:
    upload_tmp = tempfile.TemporaryDirectory(prefix="iphonevid_in_")
    root = Path(upload_tmp.name)
    ext = Path(file.filename or "video.mp4").suffix.lower() or ".mp4"
    if ext not in {".mp4", ".mov", ".webm", ".mkv", ".m4v"}:
        ext = ".mp4"
    src = root / f"input{ext}"

    out_tmp: tempfile.TemporaryDirectory | None = None
    try:
        await _save_upload(file, src)
        if src.stat().st_size == 0:
            raise HTTPException(400, "Empty file")

        out_path, meta, out_tmp = await asyncio.to_thread(process_file, src, file.filename)

        def cleanup() -> None:
            if out_tmp:
                out_tmp.cleanup()
            upload_tmp.cleanup()

        return FileResponse(
            path=out_path,
            media_type="video/mp4",
            filename=f"iphone_{Path(file.filename).stem}.mp4",
            headers={
                "X-Input-Duration": str(meta["input"]["duration"]),
                "X-Output-Size": str(meta["size_bytes"]),
            },
            background=BackgroundTask(cleanup),
        )
    except HTTPException:
        upload_tmp.cleanup()
        if out_tmp:
            out_tmp.cleanup()
        raise
    except RuntimeError as exc:
        upload_tmp.cleanup()
        if out_tmp:
            out_tmp.cleanup()
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        upload_tmp.cleanup()
        if out_tmp:
            out_tmp.cleanup()
        raise HTTPException(500, f"Processing failed: {exc}") from exc