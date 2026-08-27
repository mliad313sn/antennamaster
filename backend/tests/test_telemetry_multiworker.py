"""The live twin must be the same world in every worker.

The documented launch path runs uvicorn with `--workers 2`, and the telemetry
engine kept its registry in a module-level dict — invisible to a sibling
process. Measured on the running stack before this fix: one ingest, then eight
consecutive `/state` reads returned **2, 1, 2, 2, 2, 2, 2, 2** assets. The Live
Operations dashboard showed a fleet that flickered in and out of existence, and
the demo feed produced no assets at all often enough to look simply broken.

`results_store` had already learned this for rasters and says so in its own
docstring ("invisible to sibling uvicorn workers"). Telemetry was left behind.

Spawning two real uvicorn workers inside pytest would be slow and flaky, so
these tests assert the property that makes the multi-worker case work: nothing
the API returns may come from process-local memory. Wipe every in-process
cache between the write and the read — that is exactly what "a different
worker serves it" means — and the data must still be there.
"""
import time

import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.telemetry as telemetry
import app.services.telemetry_store as store
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    store.reset()
    return TestClient(app)


def become_another_worker():
    """Drop everything a single process could be remembering.

    After this, anything the API can still tell you came from the shared
    store — which is the whole claim.
    """
    telemetry.ENGINE.reset()
    telemetry.reset_engines()
    with store._predicates_lock:
        store._predicates.clear()


PING = {"pings": [{"asset_id": "truck-7", "name": "Haul truck 7",
                   "lat": 47.05, "lon": 15.05}]}


def test_an_asset_ingested_by_one_worker_is_visible_to_another(client):
    assert client.post("/api/telemetry/ingest", json=PING).status_code == 200

    become_another_worker()

    body = client.get("/api/telemetry/state").json()
    names = [a["name"] for a in body["assets"]]
    assert names == ["Haul truck 7"], (
        "the fleet vanished when the read was served from a clean process - "
        "the state is still process-local")


def test_repeated_reads_do_not_flicker(client):
    """The symptom as it actually presented: alternating counts."""
    client.post("/api/telemetry/ingest", json=PING)
    client.post("/api/telemetry/ingest", json={
        "pings": [{"asset_id": "loader-2", "lat": 47.06, "lon": 15.06}]})

    counts = []
    for _ in range(8):
        become_another_worker()          # a different worker each time
        counts.append(len(client.get("/api/telemetry/state").json()["assets"]))
    assert counts == [2] * 8, f"asset count flickered: {counts}"


def test_correlation_events_survive_the_worker_that_raised_them(client):
    """An operator reading the event log must see disconnects and dead-zone
    entries whichever worker answers - the log is the audit trail of the
    twin, not a per-process side effect."""
    client.post("/api/telemetry/ingest", json=PING)
    become_another_worker()

    body = client.get("/api/telemetry/events?since=0").json()
    assert body["event_seq"] >= 1
    assert any(e["type"] == "asset_online" for e in body["events"])
    # And the cursor keeps meaning the same thing across workers.
    become_another_worker()
    assert client.get(
        f"/api/telemetry/events?since={body['event_seq']}").json()["events"] == []


def test_timestamps_are_wall_clock_so_they_survive_the_crossing(client):
    """`time.monotonic()`'s epoch is arbitrary and per-process.

    Sharing those numbers between workers would make an asset look either
    impossibly stale or stale in the future, so the 30 s disconnect sweep
    would fire at random. Monotonic was the right choice while the state
    never left the process; it stopped being right the moment it did.
    """
    before = time.time()
    client.post("/api/telemetry/ingest", json=PING)
    after = time.time()

    become_another_worker()
    asset = client.get("/api/telemetry/state").json()["assets"][0]
    assert before - 1 <= asset["last_seen"] <= after + 1, (
        f"last_seen={asset['last_seen']} is not a wall-clock stamp")


def test_the_coverage_binding_survives_too(client):
    """The RF predicate closes over the terrain service and cannot be
    serialised, so the *request* is stored and each worker rebuilds its own.
    A worker that never handled the binding must still correlate."""
    r = client.post("/api/telemetry/coverage-context", json={
        "tx_lat": 47.0, "tx_lon": 15.0, "technology": "pmr446"})
    assert r.status_code == 200, r.text

    become_another_worker()

    ctx = client.get("/api/telemetry/state").json()["coverage_context"]
    assert ctx["tx_lat"] == 47.0 and ctx["technology"] == "pmr446"

    # ...and the rebuilt predicate actually runs: an ingested asset comes back
    # with a margin, which only the coverage correlation can supply.
    become_another_worker()
    asset = client.post("/api/telemetry/ingest", json=PING).json()["assets"][0]
    assert asset["margin_db"] is not None, (
        "a worker that did not handle the binding failed to rebuild the "
        "predicate, so nothing is correlated there")


def test_two_independent_sessions_see_the_same_world(client):
    """Directly, at the store: what one transaction writes, the next reads."""
    with store.shared("local") as eng:
        eng.ingest("probe", 47.0, 15.0, time.time(), name="Probe")
    with store.shared("local", write=False) as eng:
        assert [a.name for a in eng.assets.values()] == ["Probe"]


def test_a_long_silent_asset_leaves_the_live_twin(client):
    """Sharing the state made it durable, and durable made this a leak.

    While the twin lived in one process, a restart emptied it. Now nothing
    does: an asset is flagged `transmitting=False` at 30 s and then stays in
    the fleet list forever, so the panel an operator scans during an incident
    fills with vehicles that stopped mattering days ago. The disconnect
    belongs in the event log - which keeps it - not in the *live* picture.
    """
    from app.services.telemetry import RETIRE_AFTER_S

    client.post("/api/telemetry/ingest", json=PING)
    with store.shared("local", write=False) as eng:
        assert len(eng.assets) == 1

    # Half an hour of silence: disconnected, but still the fleet's business.
    with store.shared("local") as eng:
        eng.sweep(time.time() + 1800.0)
        assert [a.transmitting for a in eng.assets.values()] == [False]

    with store.shared("local") as eng:
        eng.sweep(time.time() + RETIRE_AFTER_S + 60.0)
    with store.shared("local", write=False) as eng:
        assert eng.assets == {}, "a radio silent for over an hour is not live"

    # The record survives where it belongs: the event log.
    body = client.get("/api/telemetry/events?since=0").json()
    assert any(e["type"] == "rf_disconnect" for e in body["events"])


def test_tenants_stay_separate_in_the_shared_store(client):
    """Sharing the state must not undo the tenant isolation it sits inside:
    live asset positions are the locations of real crews."""
    with store.shared("org:acme") as eng:
        eng.ingest("acme-1", 47.0, 15.0, time.time(), name="ACME truck")
    with store.shared("org:other", write=False) as eng:
        assert eng.assets == {}
    assert set(store.tenants()) >= {"org:acme"}
