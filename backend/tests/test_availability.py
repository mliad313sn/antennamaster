"""Tests: P.530 annual availability engine (C5)."""
import math

import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.rf.availability import (RAIN_ZONES_R001, geoclimatic_factor,
                                          link_availability,
                                          multipath_outage_pct,
                                          rain_attenuation_001,
                                          rain_outage_pct)
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


# ---------------------------------------------------------- formula anchors
def test_multipath_formula_self_check():
    """Recompute the published P.530 quick-method formula independently and
    require exact agreement."""
    d, f, ht, hr, m, dn1 = 30.0, 18.0, 450.0, 420.0, 35.0, -300.0
    k = 10.0 ** (-4.6 - 0.0027 * dn1)
    eps_p = abs(ht - hr) / d / 1000.0 * 1000.0
    p0 = k * d ** 3.4 * (1 + abs(eps_p)) ** -1.03 * f ** 0.8 \
        * 10.0 ** (-0.00076 * min(ht, hr))
    expected = p0 * 10.0 ** (-m / 10.0)
    got = multipath_outage_pct(d, f, ht, hr, m, dn1)
    assert got == pytest.approx(expected, rel=1e-12)
    assert geoclimatic_factor(-300.0) == pytest.approx(10.0 ** (-3.79), rel=1e-12)


def test_multipath_monotonicities():
    base = multipath_outage_pct(30, 18, 450, 420, 35)
    assert multipath_outage_pct(50, 18, 450, 420, 35) > base   # longer hop
    assert multipath_outage_pct(30, 38, 450, 420, 35) > base   # higher band
    assert multipath_outage_pct(30, 18, 450, 420, 45) < base   # more margin


def test_rain_zone_and_outage():
    # Heavier rain zone -> more 0.01% attenuation at 18 GHz.
    a_k = rain_attenuation_001(20.0, 18.0, "K")
    a_p = rain_attenuation_001(20.0, 18.0, "P")
    assert a_p > a_k > 0
    # A margin far above the 1%-scaled fade -> zero rain outage; a margin
    # below the fade at 1% -> the dire-link cap.
    assert rain_outage_pct(20.0, 18.0, "K", fade_margin_db=400.0) == 0.0
    assert rain_outage_pct(20.0, 18.0, "P", fade_margin_db=0.5) == 1.0
    # Bisection consistency: at the returned p, the fade equals the margin.
    m = 20.0
    p = rain_outage_pct(20.0, 18.0, "K", m)
    if 0 < p < 1:
        a001 = rain_attenuation_001(20.0, 18.0, "K")
        fade = a001 * 0.12 * p ** -(0.546 + 0.043 * math.log10(p))
        assert fade == pytest.approx(m, rel=1e-3)
    with pytest.raises(ValueError):
        rain_attenuation_001(20.0, 18.0, "Z")


def test_link_availability_composition_and_nines():
    res = link_availability(25.0, 18.0, 500.0, 470.0, fade_margin_db=40.0,
                            rain_zone="K")
    # Fields are rounded independently (5 vs 6 decimals) — allow that.
    assert res["availability_pct"] == pytest.approx(
        100.0 - res["total_outage_pct"], abs=1e-4)
    # Components are rounded to 1e-6 independently, so allow that granularity.
    assert res["total_outage_pct"] == pytest.approx(
        res["multipath_outage_pct"] + res["rain_outage_pct"], abs=2e-6)
    assert "nines" in res and res["downtime_minutes_per_year"] >= 0
    # A generous margin on a short hop must reach at least four nines.
    good = link_availability(8.0, 18.0, 500.0, 495.0, fade_margin_db=45.0,
                             rain_zone="E")
    assert good["availability_pct"] >= 99.99


# ------------------------------------------------------------- API layer
def test_availability_api(client):
    r = client.get("/api/terrain/availability", params={
        "lat1": 47.0, "lon1": 15.0, "lat2": 47.0, "lon2": 15.15,
        "h_tx_m": 30, "h_rx_m": 30, "technology": "ptp18000",
        "rain_zone": "K"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert 0.0 <= d["availability_pct"] <= 100.0
    assert d["rain_zone"] == "K"
    assert "link" in d and "margin_db" in d["link"]
    # Explicit margin override changes the verdict deterministically.
    hi = client.get("/api/terrain/availability", params={
        "lat1": 47.0, "lon1": 15.0, "lat2": 47.0, "lon2": 15.15,
        "technology": "ptp18000", "fade_margin_db": 50}).json()
    lo = client.get("/api/terrain/availability", params={
        "lat1": 47.0, "lon1": 15.0, "lat2": 47.0, "lon2": 15.15,
        "technology": "ptp18000", "fade_margin_db": 5}).json()
    assert hi["availability_pct"] >= lo["availability_pct"]


def test_availability_rejects_bad_zone(client):
    r = client.get("/api/terrain/availability", params={
        "lat1": 47.0, "lon1": 15.0, "lat2": 47.0, "lon2": 15.1,
        "rain_zone": "Z"})
    assert r.status_code == 422
