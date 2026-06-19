"""In-memory job queue (single worker — WEB_CONCURRENCY=1)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from processor import process_to_iphone_look

JobStatus = Literal["queued", "processing", "done", "error"]


@dataclass
class Job:
    id: str
    filename: str
    status: JobStatus = "queued"
    error: str = ""
    output_path: Path | None = None
    work_dir: Path | None = None
    created_at: float = field(default_factory=time.time)


_lock = threading.Lock()
_jobs: dict[str, Job] = {}


def create_job(src: Path, filename: str, work_dir: Path) -> Job:
    job = Job(
        id=uuid.uuid4().hex[:12],
        filename=filename,
        work_dir=work_dir,
    )
    with _lock:
        _jobs[job.id] = job
    thread = threading.Thread(target=_run_job, args=(job.id, src), daemon=True)
    thread.start()
    return job


def get_job(job_id: str) -> Job | None:
    with _lock:
        return _jobs.get(job_id)


def _run_job(job_id: str, src: Path) -> None:
    job = get_job(job_id)
    if not job or not job.work_dir:
        return

    with _lock:
        job.status = "processing"

    dst = job.work_dir / "output.mp4"
    try:
        process_to_iphone_look(src, dst)
        with _lock:
            job.status = "done"
            job.output_path = dst
    except Exception as exc:
        with _lock:
            job.status = "error"
            job.error = str(exc)[:500]
    finally:
        try:
            src.unlink(missing_ok=True)
        except OSError:
            pass


def cleanup_job(job_id: str) -> None:
    with _lock:
        job = _jobs.pop(job_id, None)
    if not job or not job.work_dir:
        return
    import shutil

    shutil.rmtree(job.work_dir, ignore_errors=True)