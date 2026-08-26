"""Cancelling a running simulation.

A full-resolution sweep is ~26 s of compute. Without cancellation a run
started with the wrong parameters must be waited out while holding one of the
four worker slots. Cancellation is cooperative — the simulation reports
progress from inside its hot loop and that callback is where the flag is
checked — so these tests assert the loop actually stops and the slot is freed.
"""
import threading
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.saas import jobs


@pytest.fixture
def client():
    return TestClient(app)


def _wait(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.02)
    return False


def test_cancel_stops_the_work_and_reports_cancelled():
    started = threading.Event()
    iterations = {"n": 0}
    job_id = jobs.create_job("test")

    def work():
        # Stand-in for the coverage sweep: long, and reports progress from
        # inside its loop exactly like CoverageEngine does.
        for i in range(400):
            iterations["n"] = i
            started.set()
            jobs.set_progress(job_id, i / 400)
            jobs.raise_if_cancelled(job_id)
            time.sleep(0.005)
        return {"finished": True}

    jobs.run_in_thread(job_id, work)
    assert started.wait(2.0), "job never started"

    assert jobs.cancel_job(job_id) is True
    assert _wait(lambda: jobs.get_job(job_id)["status"] == "cancelled")

    job = jobs.get_job(job_id)
    assert job["status"] == "cancelled"
    assert job["result"] is None
    # Cancelling is a normal outcome, not a failure: no scary error text.
    assert job["error"] is None
    # It really stopped early rather than running to completion.
    assert iterations["n"] < 399

    # The worker slot was released, so the next job can start.
    assert _wait(lambda: jobs._running == 0)


def test_cancelling_a_finished_job_is_a_no_op():
    job_id = jobs.create_job("test")
    jobs.run_in_thread(job_id, lambda: {"ok": True})
    assert _wait(lambda: jobs.get_job(job_id)["status"] == "done")
    # Too late to cancel - and we say so rather than pretending.
    assert jobs.cancel_job(job_id) is False
    assert jobs.get_job(job_id)["status"] == "done"


def test_cancel_of_unknown_job_is_false():
    assert jobs.cancel_job("nosuchjob") is False


def test_uncancelled_job_never_raises():
    job_id = jobs.create_job("test")
    jobs.raise_if_cancelled(job_id)          # must not raise
    jobs.cancel_job(job_id)
    with pytest.raises(jobs.JobCancelled):
        jobs.raise_if_cancelled(job_id)


def test_cancel_endpoint_is_owner_scoped(client):
    """A stranger must not be able to kill someone else's simulation, and
    must not learn that it exists (404, not 403)."""
    import time as _t
    email = f"jc{_t.time_ns()}@x.io"
    reg = client.post("/api/auth/register",
                      json={"email": email, "password": "hunter2hunter2"})
    assert reg.status_code == 200
    hdrs = {"Authorization": f"Bearer {reg.json()['token']}"}

    job_id = jobs.create_job("coverage", owner_id=reg.json()["user"]["id"])
    jobs.run_in_thread(job_id, lambda: {"ok": True})
    assert _wait(lambda: jobs.get_job(job_id)["status"] == "done")

    # Anonymous caller gets 404 (no existence oracle).
    assert client.delete(f"/api/saas/jobs/{job_id}").status_code == 404
    # The owner reaches it (already finished -> cancelling False, not an error).
    r = client.delete(f"/api/saas/jobs/{job_id}", headers=hdrs)
    assert r.status_code == 200 and r.json()["cancelling"] is False

    assert client.delete("/api/saas/jobs/deadbeef").status_code == 404
