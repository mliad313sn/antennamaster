"""Tests: live telemetry engine — dead-zone correlation, RF-disconnect, API."""
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.telemetry import TelemetryEngine, ENGINE
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    ENGINE.reset()
    return TestClient(app)


# ------------------------------------------------------------- unit: engine
def test_ingest_tracks_and_emits_online():
    eng = TelemetryEngine()
    eng.ingest("truck-1", 47.0, 15.0, now=100.0, name="Truck 1")
    snap = eng.snapshot()
    assert len(snap["assets"]) == 1
    a = snap["assets"][0]
    assert a["asset_id"] == "truck-1" and a["transmitting"] is True
    assert a["track"] == [[47.0, 15.0]]
    assert any(e["type"] == "asset_online" for e in eng.events_since(0))


def test_dead_zone_transition_events():
    eng = TelemetryEngine()
    # Served everywhere with positive longitude, dead-zone for negative lon.
    eng.set_coverage(lambda lat, lon: (lon > 0, 10.0 if lon > 0 else -20.0),
                     {"tx_lat": 0, "tx_lon": 0})
    eng.ingest("a", 47.0, 15.0, now=1.0)      # served
    assert eng.assets["a"].in_dead_zone is False
    eng.ingest("a", 47.0, -15.0, now=2.0)     # enters dead zone
    assert eng.assets["a"].in_dead_zone is True
    eng.ingest("a", 47.0, 15.0, now=3.0)      # exits
    types = [e["type"] for e in eng.events_since(0)]
    assert "enter_dead_zone" in types and "exit_dead_zone" in types
    # Enter must precede exit.
    assert types.index("enter_dead_zone") < types.index("exit_dead_zone")


def test_rf_disconnect_correlates_with_dead_zone():
    eng = TelemetryEngine()
    eng.set_coverage(lambda lat, lon: (False, -30.0), {"tx_lat": 0, "tx_lon": 0})
    eng.ingest("miner-7", 47.0, -15.0, now=1000.0)   # in a dead zone
    # No new ping; sweep well past the timeout.
    fired = eng.sweep(now=1000.0 + 40.0, timeout_s=30.0)
    assert len(fired) == 1
    ev = fired[0]
    assert ev["type"] == "rf_disconnect"
    assert ev["in_dead_zone"] is True
    assert ev["correlation"] == "predicted-dead-zone"
    assert eng.assets["miner-7"].transmitting is False
    # A fresh ping brings it back online (reconnect event).
    eng.ingest("miner-7", 47.0, -15.0, now=1100.0)
    assert eng.assets["miner-7"].transmitting is True
    assert any(e["type"] == "asset_reconnect" for e in eng.events_since(0))


def test_sweep_does_not_double_fire():
    eng = TelemetryEngine()
    eng.ingest("x", 47.0, 15.0, now=0.0)
    assert len(eng.sweep(now=100.0, timeout_s=30.0)) == 1
    assert len(eng.sweep(now=200.0, timeout_s=30.0)) == 0   # already down


# ------------------------------------------------------------- API layer
def test_ingest_and_state_api(client):
    r = client.post("/api/telemetry/ingest", json={"pings": [
        {"asset_id": "v1", "lat": 47.0, "lon": 15.0, "name": "Van 1"},
        {"asset_id": "v2", "lat": 47.1, "lon": 15.1}]})
    assert r.status_code == 200, r.text
    assert r.json()["ingested"] == 2
    snap = client.get("/api/telemetry/state").json()
    assert len(snap["assets"]) == 2


def test_coverage_context_and_dead_zone_api(client):
    # Bind a low-power LoRa TX; a far asset should be a predicted dead zone.
    ctx = client.post("/api/telemetry/coverage-context", json={
        "tx_lat": 47.0, "tx_lon": 15.0, "technology": "pmr446",
        "tx_power_dbm": 20.0})
    assert ctx.status_code == 200, ctx.text
    client.post("/api/telemetry/ingest", json={"pings": [
        {"asset_id": "near", "lat": 47.0, "lon": 15.001},
        {"asset_id": "far", "lat": 47.0, "lon": 15.9}]})
    snap = client.get("/api/telemetry/state").json()
    far = next(a for a in snap["assets"] if a["asset_id"] == "far")
    near = next(a for a in snap["assets"] if a["asset_id"] == "near")
    assert far["in_dead_zone"] is True
    assert near["margin_db"] > far["margin_db"]


def test_events_api(client):
    client.post("/api/telemetry/ingest", json={"pings": [
        {"asset_id": "e1", "lat": 47.0, "lon": 15.0}]})
    ev = client.get("/api/telemetry/events?since=0").json()
    assert any(e["type"] == "asset_online" for e in ev["events"])


def test_websocket_ingest(client):
    with client.websocket_connect("/api/telemetry/ws") as ws:
        ws.send_json({"asset_id": "ws1", "lat": 47.0, "lon": 15.0, "name": "WS"})
        reply = ws.receive_json()
        assert reply["ok"] is True
        assert reply["asset"]["asset_id"] == "ws1"
    assert any(a["asset_id"] == "ws1"
               for a in client.get("/api/telemetry/state").json()["assets"])


# ------------------------------------------------ multi-tenant isolation
def test_telemetry_is_open_when_self_hosted(client):
    """A single-tenant self-hosted deployment stays exactly as it was: no
    account needed, one shared live-operations view."""
    r = client.post("/api/telemetry/ingest", json={"pings": [
        {"asset_id": "truck-1", "lat": 47.0, "lon": 15.0, "name": "Truck 1"}]})
    assert r.status_code == 200
    assert client.get("/api/telemetry/state").status_code == 200


def test_telemetry_requires_auth_and_is_tenant_scoped_in_saas(client, monkeypatch):
    """Live asset positions are the real-time locations of responders, mine
    crews and field staff.

    Regression: every telemetry route was unauthenticated against ONE
    process-global engine, so anyone who could reach the backend could read
    another operator's fleet and inject forged pings into it.
    """
    import time as _t
    from app.services.telemetry import reset_engines
    reset_engines()

    def _reg(email, org):
        r = client.post("/api/auth/register", json={
            "email": email, "password": "hunter22secure", "org_name": org})
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['token']}"}

    a = _reg(f"a{_t.time_ns()}@x.io", f"AlphaFleet{_t.time_ns()}")
    b = _reg(f"b{_t.time_ns()}@x.io", f"BravoFleet{_t.time_ns()}")
    monkeypatch.setenv("AM_SAAS_MODE", "1")

    # Anonymous access is refused outright.
    assert client.get("/api/telemetry/state").status_code == 401
    assert client.post("/api/telemetry/ingest", json={"pings": [
        {"asset_id": "x", "lat": 47.0, "lon": 15.0}]}).status_code == 401

    # Tenant A tracks a crew member.
    assert client.post("/api/telemetry/ingest", json={"pings": [
        {"asset_id": "crew-7", "lat": 47.0, "lon": 15.0, "name": "Crew 7"}]},
        headers=a).status_code == 200
    mine = client.get("/api/telemetry/state", headers=a).json()
    assert any(x["asset_id"] == "crew-7" for x in mine["assets"])

    # Tenant B sees none of it, and cannot inject into A's fleet.
    theirs = client.get("/api/telemetry/state", headers=b).json()
    assert not any(x["asset_id"] == "crew-7" for x in theirs["assets"])
    client.post("/api/telemetry/ingest", json={"pings": [
        {"asset_id": "forged", "lat": 0.0, "lon": 0.0}]}, headers=b)
    still_mine = client.get("/api/telemetry/state", headers=a).json()
    assert not any(x["asset_id"] == "forged" for x in still_mine["assets"])
    reset_engines()
