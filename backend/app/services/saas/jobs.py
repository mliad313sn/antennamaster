"""Background job runner with live progress for heavy simulations.

FastAPI BackgroundTasks + a thread: the POST returns a job id immediately,
the simulation runs off the request thread reporting per-radial progress,
and the UI polls GET /api/jobs/{id} to drive a progress bar. Job state is
in-memory per worker plus a JSON sidecar on disk so a poll landing on a
sibling worker still resolves once the job completes.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from typing import Any, Callable

from ...config import DATA_DIR

JOBS_DIR = DATA_DIR / "jobs"
JOBS_DIR.mkdir(parents=True, exist_ok=True)

_jobs: dict[str, dict] = {}
_lock = threading.Lock()
_MAX_JOBS = 100


def create_job(kind: str) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        _jobs[job_id] = {"id": job_id, "kind": kind, "status": "queued",
                         "progress": 0.0, "result": None, "error": None,
                         "created_at": time.time()}
        while len(_jobs) > _MAX_JOBS:
            oldest = min(_jobs, key=lambda k: _jobs[k]["created_at"])
            _jobs.pop(oldest)
    return job_id


def set_progress(job_id: str, fraction: float) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id]["progress"] = round(min(max(fraction, 0.0), 1.0), 3)
            _jobs[job_id]["status"] = "running"


def finish_job(job_id: str, result: dict | None, error: str | None = None) -> None:
    with _lock:
        if job_id not in _jobs:
            return
        _jobs[job_id].update(status="failed" if error else "done",
                             progress=1.0, result=result, error=error)
        snapshot = dict(_jobs[job_id])
    # Disk sidecar: lets any worker answer the poll after completion.
    (JOBS_DIR / f"{job_id}.json").write_text(json.dumps(snapshot))


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
    if job is not None:
        return dict(job)
    path = JOBS_DIR / f"{''.join(c for c in job_id if c.isalnum())}.json"
    if path.exists():
        return json.loads(path.read_text())
    return None


def run_in_thread(job_id: str, fn: Callable[..., dict], *args: Any,
                  **kwargs: Any) -> None:
    """Execute fn(*args, **kwargs) in a daemon thread bound to the job."""

    def _run() -> None:
        try:
            finish_job(job_id, fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001 - job errors surface via status
            finish_job(job_id, None, error=str(exc))

    threading.Thread(target=_run, daemon=True).start()
