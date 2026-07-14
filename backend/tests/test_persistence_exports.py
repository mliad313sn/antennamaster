"""Restart/multi-worker persistence and export endpoints."""
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.dxf.store import get_dxf_store
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion", TerrainFusionService(store=fake_store))
    return TestClient(app)


def _georeference(client, site_dxf):
    with open(site_dxf, "rb") as fh:
        up = client.post("/api/dxf/upload",
                         files={"file": ("site.dxf", fh, "application/dxf")})
    dxf_id = up.json()["dxf_id"]
    resp = client.post(f"/api/dxf/{dxf_id}/georeference", json={
        "mode": "origin_bearing", "layers": ["SURVEY_POINTS", "CONTOURS"],
        "origin_lat": 47.0, "origin_lon": 15.0, "unit_scale": 1.0})
    assert resp.status_code == 200, resp.text
    return dxf_id


def test_georef_survives_process_restart(client, site_dxf):
    """Simulate a worker restart: wipe the in-memory session map, then hit
    endpoints that need the grid - they must rebuild from the sidecar."""
    dxf_id = _georeference(client, site_dxf)

    # Nuke in-process state (what a restart / sibling worker sees).
    get_dxf_store()._sessions.clear()

    state = client.get(f"/api/dxf/{dxf_id}/state")
    assert state.status_code == 200, state.text
    assert len(state.json()["footprint"]) == 4

    get_dxf_store()._sessions.clear()
    prof = client.get("/api/terrain/profile", params={
        "lat1": 47.0, "lon1": 14.97, "lat2": 47.006, "lon2": 15.008,
        "samples": 64, "dxf_id": dxf_id})
    assert prof.status_code == 200, prof.text
    assert any(p["source"] == "dxf" for p in prof.json()["points"])


def test_coverage_png_and_kmz_survive_restart(client):
    resp = client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "gsm900", "radius_km": 4,
        "n_radials": 36, "n_steps": 30})
    assert resp.status_code == 200, resp.text
    cid = resp.json()["coverage_id"]

    # Wipe the in-memory results cache (module-level _mem in results_store).
    from app.services import results_store
    results_store._mem.clear()

    png = client.get(f"/api/rf/coverage/{cid}.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    kmz = client.get(f"/api/rf/coverage/{cid}.kmz")
    assert kmz.status_code == 200
    assert kmz.content[:2] == b"PK"           # zip magic
    assert b"doc.kml" in kmz.content[:400]


def test_profile_csv_export(client):
    resp = client.get("/api/terrain/profile.csv", params={
        "lat1": 47.0, "lon1": 14.9, "lat2": 47.0, "lon2": 15.05,
        "samples": 32, "technology": "gsm900"})
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines[2].startswith("distance_m,lat,lon,")
    assert "rx_power_dbm" in lines[2]         # technology study included
    assert len(lines) == 3 + 32


def test_coverage_tilt_and_fade_margin(client):
    base = {"lat": 47.0, "lon": 15.0, "technology": "gsm900",
            "radius_km": 25, "n_radials": 36, "n_steps": 40}
    plain = client.post("/api/rf/coverage", json=base).json()
    faded = client.post("/api/rf/coverage",
                        json={**base, "shadow_margin_db": 8}).json()
    tilted = client.post("/api/rf/coverage",
                         json={**base, "antenna_azimuth_deg": 0,
                               "downtilt_deg": 8}).json()
    # A fade margin strictly reduces the served area.
    assert faded["stats"]["served_area_fraction"] < plain["stats"]["served_area_fraction"]
    # Steep downtilt pulls energy out of the far field -> less served area
    # than the plain omni case for the same power.
    assert tilted["stats"]["served_area_fraction"] < plain["stats"]["served_area_fraction"]


def test_ready_endpoint(client):
    resp = client.get("/api/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["data_dir_writable"] is True
