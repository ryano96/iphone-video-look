"""iPhone Video Look — upload AI video, download phone-style version."""

from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from processor import process_upload

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

app = FastAPI(title="iPhone Video Look", version="1.0.0")

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


@app.post("/api/process")
async def process_video(file: UploadFile = File(...)) -> FileResponse:
    if not file.filename:
        raise HTTPException(400, "No file provided")

    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")

    tmp_holder = None
    try:
        out_path, meta, tmp_holder = process_upload(data, file.filename)
        # FileResponse will stream; temp dir cleaned up after response in background
        # Keep reference on response object
        return FileResponse(
            path=out_path,
            media_type="video/mp4",
            filename=f"iphone_{Path(file.filename).stem}.mp4",
            headers={
                "X-Input-Duration": str(meta["input"]["duration"]),
                "X-Output-Size": str(meta["size_bytes"]),
            },
            background=BackgroundTask(tmp_holder.cleanup),
        )
    except RuntimeError as exc:
        if tmp_holder:
            tmp_holder.cleanup()
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        if tmp_holder:
            tmp_holder.cleanup()
        raise HTTPException(500, f"Processing failed: {exc}") from exc