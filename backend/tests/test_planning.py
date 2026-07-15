"""Tests: batch receiver qualification, height optimizer, dual-k refraction
reliability, best-site search."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.rf.planning import (evaluate_receiver, min_height_m,
                                      refraction_reliability, site_search)
from app.services.rf.technologies import get_technology
from app.services.terrain.coverage import CoverageEngine
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


# ---------------------------------------------------------- unit: heights
def _obstacle_profile():
    """Flat 10 km path with a 40 m hill in the middle."""
    d = np.linspace(0, 10_000, 201)
    e = np.full_like(d, 100.0)
    e += 40.0 * np.exp(-((d - 5_000) / 400.0) ** 2)
    return d, e


def test_min_height_bisection():
    d, e = _obstacle_profile()
    # 10 m antennas are blocked by the 40 m hill; the optimizer must find
    # a finite minimum that indeed clears, and lower heights must not.
    h = min_height_m(d, e, 5800.0, fixed_other_m=10.0, optimize="tx",
                     criterion="los")
    assert h is not None and 10.0 < h <= 120.0
    from app.services.rf.physics import analyze_path
    assert analyze_path(d, e, h + 0.1, 10.0, 5800.0)["line_of_sight_clear"]
    assert not analyze_path(d, e, max(h - 2.0, 0.0), 10.0,
                            5800.0)["line_of_sight_clear"]
    # The Fresnel criterion needs strictly more height than bare LOS.
    h_f1 = min_height_m(d, e, 5800.0, fixed_other_m=10.0, optimize="tx",
                        criterion="f1_60")
    assert h_f1 is not None and h_f1 > h
    # Unachievable: a 500 m wall.
    e2 = e.copy(); e2[95:105] = 600.0
    assert min_height_m(d, e2, 5800.0, 10.0, "tx", "los") is None
    # Already clear -> 0.
    flat = np.full_like(d, 100.0)
    assert min_height_m(d, flat, 5800.0, 30.0, "tx", "los") == 0.0


def test_refraction_reliability_dual_k():
    d, e = _obstacle_profile()
    # Generous heights: reliable under both k values.
    good = refraction_reliability(d, e, 80.0, 80.0, 18_000.0)
    assert good["reliable"] and good["clear_k43_100pct_f1"]
    # Grazing heights: k=2/3 shrinks the effective clearance and the
    # sub-refraction test must be the one that fails first.
    tight_h = 48.0
    tight = refraction_reliability(d, e, tight_h, tight_h, 18_000.0)
    assert tight["f1_ratio_k23"] < tight["f1_ratio_k43"]
    if not tight["reliable"]:
        assert not tight["clear_k23_60pct_f1"] or not tight["clear_k43_100pct_f1"]


# ------------------------------------------------------------ unit: batch
def test_evaluate_receiver_matches_expectations(fake_store):
    fusion = TerrainFusionService(store=fake_store)
    tech = get_technology("wifi5800")
    near = evaluate_receiver(fusion, dict(tech), 47.0, 15.0, 47.0, 15.01)
    far = evaluate_receiver(fusion, dict(tech), 47.0, 15.0, 47.0, 15.25)
    assert near["distance_m"] < far["distance_m"]
    assert near["rx_power_dbm"] > far["rx_power_dbm"]
    assert isinstance(near["served"], bool)
    # Clutter must strictly reduce the margin.
    clu = evaluate_receiver(fusion, dict(tech), 47.0, 15.0, 47.0, 15.01,
                            clutter_pct=90.0)
    assert clu["margin_db"] < near["margin_db"] - 5.0


# ------------------------------------------------------ unit: site search
def test_site_search_ranks_by_served_fraction(fake_store):
    engine = CoverageEngine(TerrainFusionService(store=fake_store))
    tech = get_technology("pmr446")
    res = site_search(engine, dict(tech), 46.98, 14.98, 47.02, 15.02,
                      grid_n=3, radius_m=4000.0)
    assert len(res) == 9
    fracs = [r["served_area_fraction"] for r in res]
    assert fracs == sorted(fracs, reverse=True)          # best-first
    assert [r["rank"] for r in res] == list(range(1, 10))
    assert all(0.0 <= f <= 1.0 for f in fracs)


# ------------------------------------------------------------- API layer
def test_batch_api_json_and_csv(client):
    body = {"lat": 47.0, "lon": 15.0, "technology": "lora868",
            "receivers": [{"lat": 47.0, "lon": 15.02, "name": "farm A"},
                          {"lat": 47.0, "lon": 15.05},
                          {"lat": 47.05, "lon": 15.05, "rx_height_m": 12}]}
    resp = client.post("/api/rf/batch", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["summary"]["total"] == 3
    assert data["receivers"][0]["name"] == "farm A"
    assert data["receivers"][1]["name"] == "RX 2"
    assert 0 <= data["summary"]["served_fraction"] <= 1
    assert all("margin_db" in r and "los_clear" in r
               for r in data["receivers"])

    csv = client.post("/api/rf/batch?format=csv", json=body)
    assert csv.status_code == 200
    lines = csv.text.strip().splitlines()
    assert lines[0].startswith("name,lat,lon,distance_m")
    assert len(lines) == 4
    assert "farm A" in lines[1]

    # Caps enforced.
    too_many = {**body,
                "receivers": [{"lat": 47.0, "lon": 15.0}] * 201}
    assert client.post("/api/rf/batch", json=too_many).status_code == 422


def test_optimize_heights_api(client):
    resp = client.get("/api/terrain/optimize-heights", params={
        "lat1": 47.0, "lon1": 14.95, "lat2": 47.0, "lon2": 15.05,
        "tx_height_m": 10, "rx_height_m": 10, "freq_mhz": 5800})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    for crit in ("los", "f1_60"):
        assert crit in data["criteria"]
        v = data["criteria"][crit]["min_tx_height_m"]
        assert v is None or 0.0 <= v <= 120.0
    # F1 criterion can never need less height than bare LOS.
    los_h = data["criteria"]["los"]["min_tx_height_m"]
    f1_h = data["criteria"]["f1_60"]["min_tx_height_m"]
    if los_h is not None and f1_h is not None:
        assert f1_h >= los_h


def test_profile_reports_refraction_check(client):
    resp = client.get("/api/terrain/profile", params={
        "lat1": 47.0, "lon1": 14.98, "lat2": 47.0, "lon2": 15.02,
        "samples": 64, "freq_mhz": 18000})
    assert resp.status_code == 200
    ref = resp.json()["rf"]["refraction"]
    assert set(ref) >= {"f1_ratio_k43", "f1_ratio_k23", "reliable"}
    assert ref["f1_ratio_k23"] <= ref["f1_ratio_k43"] + 1e-6


def test_site_search_api(client):
    resp = client.post("/api/rf/site-search", json={
        "south": 46.99, "west": 14.99, "north": 47.01, "east": 15.01,
        "grid_n": 2, "technology": "pmr446", "radius_km": 3})
    assert resp.status_code == 200, resp.text
    cands = resp.json()["candidates"]
    assert len(cands) == 4 and cands[0]["rank"] == 1
    # Degenerate bbox rejected.
    bad = client.post("/api/rf/site-search", json={
        "south": 47.0, "west": 15.0, "north": 46.9, "east": 15.01,
        "technology": "pmr446"})
    assert bad.status_code == 422


# -------------------------------------------------- Simple Mode scenarios
def test_scenarios_map_to_presets(client):
    r = client.get("/api/rf/scenarios")
    assert r.status_code == 200
    scs = r.json()["scenarios"]
    assert len(scs) >= 6
    ids = {s["id"] for s in scs}
    assert {"buildings_ptp", "fleet_wifi", "site_radios"} <= ids
    for s in scs:
        # i18n keys, not display text; each resolves to a real preset.
        assert s["label"].startswith("scenario.")
        assert s["study"] in ("profile", "coverage")
        assert s["technology"]
    # Resolving one returns full physics params.
    one = client.get("/api/rf/scenarios/fleet_wifi").json()
    assert one["technology"] == "wifi2400"
    assert one["study"] == "coverage" and one["radius_km"] == 3.0
    assert client.get("/api/rf/scenarios/nonexistent").status_code == 404


# --------------------------------------------------- hardware catalog
def test_hardware_catalog(client):
    r = client.get("/api/rf/equipment")
    assert r.status_code == 200
    body = r.json()
    eq = body["equipment"]
    assert len(eq) >= 10
    cats = set(body["categories"])
    assert {"Wi-Fi", "Private LTE", "PTP Microwave"} <= cats
    # Every profile carries the required planning attributes.
    for e in eq:
        for f in ("id", "vendor", "model", "category", "band_label", "freq_mhz",
                  "tx_power_dbm", "rx_sensitivity_dbm", "antenna_gain_dbi",
                  "beamwidth_deg", "technology"):
            assert f in e, f"{e.get('id')} missing {f}"
        assert e["freq_mhz"] > 0 and e["antenna_gain_dbi"] >= 0
