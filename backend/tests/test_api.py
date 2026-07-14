"""End-to-end API tests: upload -> layers -> georeference -> overlay -> profile.

The DEM store is patched to the offline FakeTileStore so no network is used.
"""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    # Route every service through the fake DEM world.
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion", TerrainFusionService(store=fake_store))
    return TestClient(app)


def _upload(client, site_dxf):
    with open(site_dxf, "rb") as fh:
        resp = client.post("/api/dxf/upload",
                           files={"file": ("site.dxf", fh, "application/dxf")})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_full_dxf_workflow(client, site_dxf, fake_store):
    # 1) Upload returns the layer inventory.
    up = _upload(client, site_dxf)
    names = {l["name"] for l in up["layers"]}
    assert {"SURVEY_POINTS", "CONTOURS", "BUILDINGS"} <= names
    dxf_id = up["dxf_id"]

    # 2) Layers endpoint agrees.
    layers = client.get(f"/api/dxf/{dxf_id}/layers").json()["layers"]
    survey = next(l for l in layers if l["name"] == "SURVEY_POINTS")
    assert survey["point_count"] > 100

    # 3) Georeference (mode C) near lon 15 in the fake ramp world.
    resp = client.post(f"/api/dxf/{dxf_id}/georeference", json={
        "mode": "origin_bearing",
        "layers": ["SURVEY_POINTS", "CONTOURS"],
        "origin_lat": 47.0, "origin_lon": 15.0,
        "bearing_deg": 0.0, "unit_scale": 1.0,
    })
    assert resp.status_code == 200, resp.text
    geo = resp.json()
    assert geo["transform"]["mode"] == "origin_bearing"
    assert len(geo["footprint"]) == 4
    assert geo["grid"]["points_used"] > 100
    # Fake SRTM near lon 15 ~= 370 m vs DXF ~230 m -> validation must warn.
    assert geo["validation"]["warning"] is not None

    # 4) Hillshade overlay renders a PNG.
    png = client.get(f"/api/dxf/{dxf_id}/overlay.png")
    assert png.status_code == 200
    assert png.content[:8] == b"\x89PNG\r\n\x1a\n"

    # 5) Fused profile crossing the site carries both provenances.
    prof = client.get("/api/terrain/profile", params={
        "lat1": 47.0, "lon1": 14.97, "lat2": 47.006, "lon2": 15.008,
        "samples": 128, "dxf_id": dxf_id,
        "tx_height_m": 20, "rx_height_m": 10, "freq_mhz": 446,
    })
    assert prof.status_code == 200, prof.text
    body = prof.json()
    sources = {p["source"] for p in body["points"]}
    assert "srtm" in sources and "dxf" in sources
    # Curvature applied: curved elevation >= raw for interior samples.
    mid = body["points"][len(body["points"]) // 2]
    assert mid["elev_curved"] > mid["elev"]
    assert "knife_edge_loss_db" in body["rf"]


def test_profile_without_dxf_is_pure_srtm(client):
    resp = client.get("/api/terrain/profile", params={
        "lat1": 47.0, "lon1": 14.9, "lat2": 47.0, "lon2": 15.1, "samples": 64,
    })
    assert resp.status_code == 200
    body = resp.json()
    assert all(p["source"] == "srtm" for p in body["points"])
    assert body["dxf_id"] is None


def test_helmert_endpoint_returns_residuals(client, site_dxf):
    dxf_id = _upload(client, site_dxf)["dxf_id"]
    resp = client.post(f"/api/dxf/{dxf_id}/georeference", json={
        "mode": "control_points",
        "layers": ["SURVEY_POINTS"],
        "control_points": [
            {"dxf_x": 0, "dxf_y": 0, "lat": 47.0, "lon": 15.0},
            {"dxf_x": 1000, "dxf_y": 0, "lat": 47.0, "lon": 15.01316},
            {"dxf_x": 0, "dxf_y": 1000, "lat": 47.008993, "lon": 15.0},
        ],
    })
    assert resp.status_code == 200, resp.text
    t = resp.json()["transform"]
    assert t["mode"] == "control_points"
    assert t["scale_m_per_unit"] == pytest.approx(1.0, rel=0.02)
    assert len(t["residuals_m"]) == 3
    assert t["rms_residual_m"] < 20.0


def test_bad_inputs(client, site_dxf):
    # Wrong extension rejected.
    resp = client.post("/api/dxf/upload",
                       files={"file": ("notes.txt", b"hello", "text/plain")})
    assert resp.status_code == 400
    # Unknown id.
    assert client.get("/api/dxf/nope/layers").status_code == 404
    # Georeference on non-terrain layers -> 422.
    dxf_id = _upload(client, site_dxf)["dxf_id"]
    resp = client.post(f"/api/dxf/{dxf_id}/georeference", json={
        "mode": "origin_bearing", "layers": ["BUILDINGS"],
        "origin_lat": 47.0, "origin_lon": 15.0,
    })
    assert resp.status_code == 422
    # Profile against un-georeferenced DXF -> 409.
    dxf_id2 = _upload(client, site_dxf)["dxf_id"]
    resp = client.get("/api/terrain/profile", params={
        "lat1": 47.0, "lon1": 14.9, "lat2": 47.0, "lon2": 15.1,
        "dxf_id": dxf_id2,
    })
    assert resp.status_code == 409
