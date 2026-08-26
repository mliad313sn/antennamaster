"""Background job runner with live progress for heavy simulations.

FastAPI BackgroundTasks + a thread: the POST returns a job id immediately,
the simulation runs off the request thread reporting per-radial progress,
and the UI polls GET /api/jobs/{id} to drive a progress bar. Job state is
in-memory per worker plus a JSON sidecar on disk so a poll landing on a
sibling worker still resolves once the job completes.
"""
from __future__ import annotations

import contextlib
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
# Hard cap on LIVE worker threads: excess submissions are rejected (429)
# instead of letting anonymous callers saturate the CPU with simulations.
MAX_RUNNING = 4
_running = 0


class JobsBusyError(RuntimeError):
    """Raised when the concurrent-job cap is reached."""


class JobCancelled(RuntimeError):
    """Raised inside a worker thread when the user cancelled the job.

    Cancellation is cooperative: the simulation reports progress from inside
    its hot loop, and that same callback is where we check the flag. There is
    no safe way to kill a thread mid-numpy, so this is the correct mechanism -
    the job stops at the next progress tick and releases its slot.
    """


def create_job(kind: str, owner_id: int | None = None) -> str:
    job_id = uuid.uuid4().hex[:12]
    snapshot = {"id": job_id, "kind": kind, "status": "queued",
                "progress": 0.0, "result": None, "error": None,
                "owner_id": owner_id, "created_at": time.time()}
    with _lock:
        _jobs[job_id] = snapshot
        while len(_jobs) > _MAX_JOBS:
            oldest = min(_jobs, key=lambda k: _jobs[k]["created_at"])
            _jobs.pop(oldest)
    # Sidecar at creation time too, so a poll landing on a sibling worker
    # resolves (as "running") before the job finishes - the module contract.
    try:
        (JOBS_DIR / f"{job_id}.json").write_text(json.dumps(dict(snapshot)))
    except OSError:
        pass
    return job_id


def owner_of(job: dict) -> int | None:
    return job.get("owner_id")


def set_progress(job_id: str, fraction: float) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id]["progress"] = round(min(max(fraction, 0.0), 1.0), 3)
            _jobs[job_id]["status"] = "running"


def cancel_job(job_id: str) -> bool:
    """Ask a running job to stop. True if it was live and is now cancelling.

    Returns False for an unknown or already-finished job, so the caller can
    tell "too late" from "cancelling" without guessing.
    """
    with _lock:
        job = _jobs.get(job_id)
        if job is None or job["status"] in ("done", "failed", "cancelled"):
            return False
        job["cancel_requested"] = True
        return True


def raise_if_cancelled(job_id: str) -> None:
    """Abort the current job if the user cancelled it. Called from the
    simulation's progress callback, which runs inside its hot loop."""
    with _lock:
        job = _jobs.get(job_id)
        if job is not None and job.get("cancel_requested"):
            raise JobCancelled("Cancelled by the user")


def finish_job(job_id: str, result: dict | None, error: str | None = None,
               cancelled: bool = False) -> None:
    with _lock:
        if job_id not in _jobs:
            return
        status = "cancelled" if cancelled else ("failed" if error else "done")
        _jobs[job_id].update(status=status, progress=1.0, result=result,
                             error=error)
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
    """Execute fn(*args, **kwargs) in a daemon thread bound to the job.
    Raises JobsBusyError when MAX_RUNNING jobs are already live."""
    global _running
    with _lock:
        if _running >= MAX_RUNNING:
            _jobs.pop(job_id, None)
            raise JobsBusyError(
                f"{MAX_RUNNING} simulations already running - retry shortly")
        _running += 1

    def _run() -> None:
        global _running
        try:
            finish_job(job_id, fn(*args, **kwargs))
        except JobCancelled:
            # A user-requested stop is a normal outcome, not a failure - it
            # must not surface as a scary error in the UI.
            finish_job(job_id, None, cancelled=True)
        except Exception as exc:  # noqa: BLE001 - job errors surface via status
            finish_job(job_id, None, error=str(exc))
        finally:
            with _lock:
                _running -= 1

    threading.Thread(target=_run, daemon=True).start()


# Concurrency cap for SYNCHRONOUS heavy simulations (coverage / multi /
# batch / site-search).  The async path is bounded by MAX_RUNNING above; the
# inline path had no cap, so a handful of max-resolution requests could pin
# every CPU.  This bounds in-flight sync sims to MAX_SYNC and answers 429
# past that.  Best-effort per worker (like the login lockout), which is the
# right granularity: it protects each worker's own CPU.
MAX_SYNC = 6
_sync_running = 0


class SimBusyError(RuntimeError):
    """Raised when the synchronous-simulation concurrency cap is reached."""


@contextlib.contextmanager
def sim_slot():
    """Acquire a synchronous-simulation slot or raise SimBusyError."""
    global _sync_running
    with _lock:
        if _sync_running >= MAX_SYNC:
            raise SimBusyError(
                f"{MAX_SYNC} simulations already running on this worker - "
                "retry shortly or use POST /api/saas/coverage/async")
        _sync_running += 1
    try:
        yield
    finally:
        with _lock:
            _sync_running -= 1
