"""API edge-case hardening: extreme/invalid payloads must return clean 4xx
validation errors, never 500s or garbage results."""
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


# ---------------------------------------------------------------- profiles
@pytest.mark.parametrize("params", [
    {"lat1": 91, "lon1": 0, "lat2": 0, "lon2": 0},          # lat out of range
    {"lat1": 0, "lon1": -181, "lat2": 0, "lon2": 0},        # lon out of range
    {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 0, "samples": 4},   # too few
    {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 0, "samples": 5000},  # too many
    {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 0, "freq_mhz": -5},
    {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 0, "k_factor": 0},
    {"lat1": 0, "lon1": 0, "lat2": 0, "lon2": 0, "rain_rate_mm_h": -1},
])
def test_profile_rejects_invalid(client, params):
    assert client.get("/api/terrain/profile", params=params).status_code == 422


def test_profile_identical_endpoints(client):
    """Zero-length path must not divide by zero anywhere."""
    r = client.get("/api/terrain/profile", params={
        "lat1": 47.0, "lon1": 15.0, "lat2": 47.0, "lon2": 15.0, "samples": 16})
    assert r.status_code == 200
    body = r.json()
    assert body["distance_m"] == pytest.approx(0.0, abs=1.0)
    assert all(abs(p["elev"]) < 10_000 for p in body["points"])


def test_profile_antimeridian_and_poles(client):
    """Paths across the antimeridian and near the poles stay finite."""
    r = client.get("/api/terrain/profile", params={
        "lat1": 0.0, "lon1": 179.9, "lat2": 0.0, "lon2": -179.9, "samples": 32})
    assert r.status_code == 200
    r2 = client.get("/api/terrain/profile", params={
        "lat1": 84.9, "lon1": 0.0, "lat2": 84.5, "lon2": 1.0, "samples": 32})
    assert r2.status_code == 200


def test_profile_unknown_technology_and_model(client):
    assert client.get("/api/terrain/profile", params={
        "lat1": 0, "lon1": 0, "lat2": 1, "lon2": 1,
        "technology": "carrier_pigeon"}).status_code == 422
    assert client.get("/api/terrain/profile", params={
        "lat1": 0, "lon1": 0, "lat2": 1, "lon2": 1,
        "technology": "gsm900", "model": "warp_drive"}).status_code == 422


# ---------------------------------------------------------------- coverage
def test_coverage_negative_gain_is_legal_but_bounded(client):
    """Negative antenna gains are physically valid (lossy antennas) and must
    compute, not crash."""
    r = client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "custom",
        "tx_gain_dbi": -10.0, "rx_gain_dbi": -3.0,
        "radius_km": 2, "n_radials": 36, "n_steps": 20})
    assert r.status_code == 200
    assert r.json()["stats"]["max_rx_power_dbm"] < 30.0


@pytest.mark.parametrize("body", [
    {"lat": 47.0, "lon": 15.0, "radius_km": 0},              # zero radius
    {"lat": 47.0, "lon": 15.0, "radius_km": 9000},           # beyond cap
    {"lat": 47.0, "lon": 15.0, "n_radials": 4},              # under floor
    {"lat": 47.0, "lon": 15.0, "downtilt_deg": 90},          # absurd tilt
    {"lat": 47.0, "lon": 15.0, "raster_px": 8000},           # raster too big
])
def test_coverage_rejects_invalid(client, body):
    assert client.post("/api/rf/coverage",
                       json={"technology": "custom", **body}).status_code == 422


def test_coverage_unknown_dxf_and_antenna(client):
    assert client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "custom",
        "dxf_id": "nope", "radius_km": 2}).status_code == 404
    assert client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "custom",
        "antenna_id": "ghost", "radius_km": 2}).status_code == 404


# --------------------------------------------------------------- DXF & misc
def test_dxf_endpoints_missing_file(client):
    assert client.get("/api/dxf/doesnotexist/layers").status_code == 404
    assert client.get("/api/dxf/doesnotexist/state").status_code == 404
    assert client.get("/api/dxf/doesnotexist/overlay.png").status_code == 404
    r = client.post("/api/dxf/upload",
                    files={"file": ("garbage.dxf", b"\x00\x01nonsense", "x")})
    assert r.status_code == 422              # parse error surfaced cleanly


def test_indoor_edge_cases(client):
    assert client.get("/api/indoor/nope/preview.png").status_code == 404
    # Tunnel with degenerate geometry rejected by validation.
    assert client.get("/api/indoor/tunnel",
                      params={"width_m": 0}).status_code == 422
    # TTE frequency bounds enforced.
    assert client.get("/api/indoor/tte",
                      params={"freq_hz": 5}).status_code == 422


def test_auth_edge_cases(client):
    # Malformed bearer tokens are treated as anonymous, not 500.
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer zzz"})
    assert r.status_code == 401
    r = client.get("/api/auth/me", headers={"Authorization": "NotBearer"})
    assert r.status_code == 401
    # Short password rejected at validation.
    assert client.post("/api/auth/register", json={
        "email": "x@y.io", "password": "short"}).status_code == 422
