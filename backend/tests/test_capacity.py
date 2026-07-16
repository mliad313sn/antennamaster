"""Tests: Erlang B/C dimensioning + SINR→throughput + saturation (C4)."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.rf.capacity import (cell_capacity, channels_for_gos,
                                      erlang_b, erlang_c, saturation,
                                      spectral_efficiency,
                                      throughput_map_mbps)
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


# --------------------------------------------------------------- Erlang
def test_erlang_b_classic_table_anchors():
    # Canonical Erlang-B table values.
    assert erlang_b(10.0, 10) == pytest.approx(0.2146, abs=1e-3)
    assert erlang_b(5.084, 10) == pytest.approx(0.02, abs=5e-4)   # 2% GoS point
    assert erlang_b(0.0, 5) == 0.0
    assert erlang_b(100.0, 0) == 1.0


def test_erlang_c_properties():
    # Erlang C >= Erlang B for the same load; saturates at N <= A.
    assert erlang_c(5.0, 10) > erlang_b(5.0, 10)
    assert erlang_c(10.0, 10) == 1.0
    assert erlang_c(12.0, 10) == 1.0


def test_channels_for_gos_inverse():
    n = channels_for_gos(5.084, 0.02, "b")
    assert n == 10
    # One channel fewer must violate the GoS.
    assert erlang_b(5.084, n - 1) > 0.02


# ---------------------------------------------------------- SINR ladder
def test_spectral_efficiency_ladder():
    eff = spectral_efficiency([-10.0, -6.7, 0.2, 22.7, 40.0])
    assert eff[0] == 0.0                       # below CQI-1: no service
    assert eff[1] == pytest.approx(0.1523)     # CQI-1 threshold
    assert eff[2] == pytest.approx(0.6016)     # CQI-4
    assert eff[3] == eff[4] == pytest.approx(5.5547)   # capped at CQI-15
    # Monotonic non-decreasing.
    grid = spectral_efficiency(np.linspace(-10, 30, 200))
    assert np.all(np.diff(grid) >= 0)


def test_throughput_and_capacity():
    tp = throughput_map_mbps([22.7], bandwidth_mhz=20.0, overhead=0.25)
    assert tp[0] == pytest.approx(5.5547 * 20.0 * 0.75, rel=1e-6)
    field = np.array([[22.7, 10.3], [-10.0, 0.2]])
    mask = np.ones((2, 2), dtype=bool)
    cap = cell_capacity(field, mask, 20.0)
    assert cap["served_pixels"] == 3           # the -10 dB pixel is unserved
    assert cap["peak_mbps"] > cap["edge_mbps"]


def test_saturation_scenario():
    ok = saturation(100.0, users=40, mbps_per_user=2.0)      # 80 < 100
    assert not ok["saturated"] and ok["load_factor"] == 0.8
    sat = saturation(100.0, users=80, mbps_per_user=2.0)     # 160 > 100
    assert sat["saturated"] and sat["max_users"] == 50


# ------------------------------------------------------------- API layer
def test_erlang_api(client):
    d = client.get("/api/rf/erlang", params={
        "traffic_erlangs": 10, "channels": 10, "gos": 0.02}).json()
    assert d["blocking_probability"] == pytest.approx(0.2146, abs=1e-3)
    # 10 E @ 2% GoS: 17 trunks (16 carry only ~9.83 E at 2%) — checked by
    # inversion rather than a remembered table value.
    n = d["channels_for_gos"]
    assert erlang_b(10.0, n) <= 0.02 < erlang_b(10.0, n - 1)
    assert client.get("/api/rf/erlang", params={
        "traffic_erlangs": 5, "kind": "x"}).status_code == 422


def test_throughput_map_api_with_saturation(client):
    sites = [{"lat": 47.0, "lon": 15.0}, {"lat": 47.03, "lon": 15.03}]
    r = client.post("/api/rf/throughput-map", json={
        "sites": sites, "technology": "private_lte_b48", "radius_km": 4,
        "n_radials": 48, "n_steps": 32, "grid_n": 96,
        "users_per_cell": 200, "mbps_per_user": 3.0})
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["cells"]) == 2
    for cell in d["cells"]:
        assert cell["capacity_mbps"] >= 0
        assert "saturation" in cell
        assert isinstance(cell["saturation"]["saturated"], bool)


def test_throughput_map_plan_reduces_interference(client):
    # Two overlapping co-channel cells vs a 2-channel plan: capacity must not
    # decrease when the interferer moves off-channel.
    sites = [{"lat": 47.0, "lon": 15.0}, {"lat": 47.01, "lon": 15.01}]
    base = {"sites": sites, "technology": "lte1800", "radius_km": 5,
            "n_radials": 48, "n_steps": 32, "grid_n": 96}
    reuse1 = client.post("/api/rf/throughput-map", json=base).json()
    planned = client.post("/api/rf/throughput-map",
                          json={**base, "channels": [0, 1]}).json()
    c0 = reuse1["cells"][0]["capacity_mbps"]
    c1 = planned["cells"][0]["capacity_mbps"]
    assert c1 >= c0
    assert planned["plan_applied"] is True


def test_throughput_map_renders_mbps_heatmap(client):
    # render=True (the default) must return a fetchable Mbit/s overlay with a
    # legend whose thresholds are absolute Mbit/s labels.
    sites = [{"lat": 47.0, "lon": 15.0}, {"lat": 47.02, "lon": 15.02}]
    r = client.post("/api/rf/throughput-map", json={
        "sites": sites, "technology": "lte1800", "radius_km": 4,
        "n_radials": 48, "n_steps": 32, "grid_n": 96, "raster_px": 256})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["png_url"].startswith("/api/rf/coverage/")
    assert len(d["bounds"]) == 2 and len(d["bounds"][0]) == 2
    assert len(d["legend"]) == 5
    assert all("Mbit/s" in step["label"] for step in d["legend"])
    assert d["raster_stats"]["peak_mbps"] <= d["raster_stats"]["ceiling_mbps"]
    png = client.get(d["png_url"])
    assert png.status_code == 200
    assert png.content[:4] == b"\x89PNG"
    # render=False keeps the response light: no raster keys at all.
    r2 = client.post("/api/rf/throughput-map", json={
        "sites": sites, "technology": "lte1800", "radius_km": 4,
        "n_radials": 48, "n_steps": 32, "grid_n": 96, "render": False})
    assert "png_url" not in r2.json()


def test_itm_route_exposes_climate_and_refractivity(client):
    # The NTIA engine's environment parameters must reach the algorithm:
    # different climate / N0 => different loss on the same path.
    base = {"lat1": 47.0, "lon1": 15.0, "lat2": 47.15, "lon2": 15.2,
            "freq_mhz": 900, "reliability": 0.9, "samples": 128}
    r0 = client.get("/api/terrain/itm", params=base)
    assert r0.status_code == 200, r0.text
    d0 = r0.json()
    assert d0["climate"] == 5 and d0["en0"] == 314.0
    d1 = client.get("/api/terrain/itm", params={**base, "climate": 1}).json()
    d2 = client.get("/api/terrain/itm", params={**base, "en0": 400}).json()
    assert d1["path_loss_db"] != d0["path_loss_db"]
    assert d2["path_loss_db"] != d0["path_loss_db"]
    assert client.get("/api/terrain/itm",
                      params={**base, "climate": 9}).status_code == 422


# ----------------------------------------------------- Monte Carlo traffic
def test_montecarlo_traffic_api(client):
    sites = [{"lat": 47.0, "lon": 15.0}, {"lat": 47.02, "lon": 15.02}]
    base = {"sites": sites, "technology": "lte1800", "radius_km": 4,
            "n_radials": 48, "n_steps": 32, "grid_n": 96, "render": False,
            "users": 150, "demand_mbps": 2.0, "draws": 40, "seed": 7}
    r = client.post("/api/rf/montecarlo", json=base)
    assert r.status_code == 200, r.text
    d = r.json()
    sf = d["satisfied_fraction"]
    assert 0.0 <= sf["p5"] <= sf["mean"] <= sf["p95"] <= 1.0
    assert len(d["cells"]) == 2
    # Reproducible: same seed -> identical distribution.
    d2 = client.post("/api/rf/montecarlo", json=base).json()
    assert d2["satisfied_fraction"] == sf
    # More offered load can never increase satisfaction (equal airtime).
    heavy = client.post("/api/rf/montecarlo",
                        json={**base, "users": 1500}).json()
    assert heavy["satisfied_fraction"]["mean"] <= sf["mean"]


def test_montecarlo_rejects_bad_inputs(client):
    sites = [{"lat": 47.0, "lon": 15.0}]
    assert client.post("/api/rf/montecarlo", json={
        "sites": sites, "technology": "lte1800", "draws": 5000}).status_code == 422
    assert client.post("/api/rf/montecarlo", json={
        "sites": sites, "technology": "lte1800",
        "demand_mbps": 0}).status_code == 422


def test_cluster_cap_raised_to_24(client):
    # 9 sites (over the old 8-cap) must be accepted by the schema.
    sites = [{"lat": 47.0 + 0.01 * i, "lon": 15.0} for i in range(9)]
    r = client.post("/api/rf/throughput-map", json={
        "sites": sites, "technology": "lte1800", "radius_km": 2,
        "n_radials": 36, "n_steps": 20, "grid_n": 64, "render": False})
    assert r.status_code == 200, r.text
    assert len(r.json()["cells"]) == 9
    # 25 is over the new cap.
    too_many = [{"lat": 47.0 + 0.01 * i, "lon": 15.0} for i in range(25)]
    assert client.post("/api/rf/throughput-map", json={
        "sites": too_many, "technology": "lte1800",
        "render": False}).status_code == 422
