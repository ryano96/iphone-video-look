"""iPhone Video Look — upload AI video, download phone-style version."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from jobs import cleanup_job, create_job, get_job
from processor import MAX_BYTES, probe_video

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
CHUNK = 1024 * 1024

app = FastAPI(title="iPhone Video Look", version="1.1.0")

if STATIC.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/health")
def health() -> dict:
    from snap_caption import FONT_CANDIDATES

    font_ok = any(Path(p).is_file() for p in FONT_CANDIDATES)
    return {
        "ok": True,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "caption_font": font_ok,
    }


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    page = STATIC / "index.html"
    if not page.exists():
        raise HTTPException(500, "UI missing")
    return HTMLResponse(page.read_text(encoding="utf-8"))


async def _save_upload(file: UploadFile, dest: Path) -> int:
    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file.read(CHUNK)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_BYTES:
                raise HTTPException(400, f"File too large (max {MAX_BYTES // (1024 * 1024)} MB).")
            out.write(chunk)
    return size


@app.post("/api/process")
async def start_process(
    file: UploadFile = File(...),
    caption: str = Form(""),
) -> JSONResponse:
    if not file.filename:
        raise HTTPException(400, "No file provided")

    work_dir = Path(tempfile.mkdtemp(prefix="iphonevid_job_"))
    ext = Path(file.filename).suffix.lower() or ".mp4"
    if ext not in {".mp4", ".mov", ".webm", ".mkv", ".m4v"}:
        ext = ".mp4"
    src = work_dir / f"input{ext}"

    try:
        size = await _save_upload(file, src)
        if size == 0:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise HTTPException(400, "Empty file")

        info = probe_video(src)
        if info["duration"] > 120:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise HTTPException(400, "Video too long (max 2 min).")

        job = create_job(src, file.filename, work_dir, caption=caption.strip())
        return JSONResponse({"job_id": job.id, "status": job.status})
    except HTTPException:
        raise
    except RuntimeError as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(500, f"Upload failed: {exc}") from exc


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    out: dict = {"job_id": job.id, "status": job.status}
    if job.status == "error":
        out["error"] = job.error
    return out


@app.get("/api/jobs/{job_id}/download")
def job_download(job_id: str) -> FileResponse:
    job = get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status == "processing" or job.status == "queued":
        raise HTTPException(409, "Still processing")
    if job.status == "error":
        raise HTTPException(400, job.error or "Processing failed")
    if not job.output_path or not job.output_path.exists():
        raise HTTPException(500, "Output file missing")

    stem = Path(job.filename).stem
    return FileResponse(
        path=job.output_path,
        media_type="video/mp4",
        filename=f"iphone_{stem}.mp4",
        background=BackgroundTask(cleanup_job, job_id),
    )