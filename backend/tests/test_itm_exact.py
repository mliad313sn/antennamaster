"""Tests: exact NTIA ITM (published validation case, ≤0.1 dB) + official P.1812."""
import numpy as np
import pytest

from app.services.rf.itm_exact import itm_p2p_loss, p1812_available, p1812_loss

# Published itmlogic point-to-point validation case: the 77.8 km Crystal
# Palace (UK) profile at 41.5 MHz, TX 143.9 m / RX 8.5 m, horizontal pol,
# eps=15, sigma=0.005, N0=314, continental temperate. Expected losses are the
# values asserted by the itmlogic project's own test suite (test_p2p.py).
CRYSTAL_PALACE_PROFILE = [
    96, 84, 65, 46, 46, 46, 61, 41, 33, 27, 23, 19, 15, 15, 15,
    15, 15, 15, 15, 15, 15, 15, 15, 15, 17, 19, 21, 23, 25, 27,
    29, 35, 46, 41, 35, 30, 33, 35, 37, 40, 35, 30, 51, 62, 76,
    46, 46, 46, 46, 46, 46, 50, 56, 67, 106, 83, 95, 112, 137, 137,
    76, 103, 122, 122, 83, 71, 61, 64, 67, 71, 74, 77, 79, 86, 91,
    83, 76, 68, 63, 76, 107, 107, 107, 119, 127, 133, 135, 137, 142, 148,
    152, 152, 107, 137, 104, 91, 99, 120, 152, 152, 137, 168, 168, 122, 137,
    137, 170, 183, 183, 187, 194, 201, 192, 152, 152, 166, 177, 198, 156, 127,
    116, 107, 104, 101, 98, 95, 103, 91, 97, 102, 107, 107, 107, 103, 98,
    94, 91, 105, 122, 122, 122, 122, 122, 137, 137, 137, 137, 137, 137, 137,
    137, 140, 144, 147, 150, 152, 159,
]
DIST_M = 77_800.0

# (confidence_pct, reliability_pct) -> expected propagation loss dB
EXPECTED = {
    (50, 1): 128.5969,
    (90, 1): 137.6428,
    (10, 1): 119.5510,
    (50, 99): 139.7413,
    (90, 99): 148.4389,
    (10, 99): 131.0436,
}


def _run(rel, conf):
    d = np.linspace(0.0, DIST_M, len(CRYSTAL_PALACE_PROFILE))
    return itm_p2p_loss(d, CRYSTAL_PALACE_PROFILE, 143.9, 8.5, 41.5,
                        reliability_pct=rel, confidence_pct=conf,
                        eps=15, sgm=0.005, en0=314, climate=5, polarization=0)


def test_itm_matches_published_reference_within_0p1_db():
    for (conf, rel), expected in EXPECTED.items():
        res = _run(rel, conf)
        assert res["path_loss_db"] == pytest.approx(expected, abs=0.1), \
            f"conf={conf} rel={rel}: {res['path_loss_db']} vs {expected}"
        assert res["error_flag_kwx"] <= 1        # no serious parameter warning


def test_itm_reliability_and_confidence_ordering():
    # More demanding quantiles must cost more loss.
    assert _run(99, 50)["path_loss_db"] > _run(1, 50)["path_loss_db"]
    assert _run(50, 90)["path_loss_db"] > _run(50, 10)["path_loss_db"]


def test_itm_rejects_tiny_profile():
    with pytest.raises(ValueError):
        itm_p2p_loss([0, 100], [10, 10], 10, 10, 900)


# ------------------------------------------------------------ ITU-R P.1812
needs_p1812 = pytest.mark.skipif(not p1812_available(),
                                 reason="Py1812 / ITU maps not installed")


def _p1812_case(dist_km=30.0, n=121, freq=900.0, clutter=None):
    d = np.linspace(0, dist_km * 1000.0, n)
    h = np.full(n, 100.0)
    lats = np.full(n, 46.0) + np.linspace(0, dist_km / 111.0, n)
    lons = np.full(n, 15.0)
    return p1812_loss(d, h, lats, lons, 30.0, 10.0, freq,
                      clutter_heights_m=clutter)


@needs_p1812
def test_p1812_official_smoke_and_physics():
    res = _p1812_case()
    assert res["engine"] == "itu_p1812_official"
    # Smooth 30 km path at 900 MHz: loss must exceed free space but stay sane.
    assert res["free_space_db"] < res["path_loss_db"] < res["free_space_db"] + 80
    # Longer path -> more loss.
    assert _p1812_case(dist_km=60.0)["path_loss_db"] > res["path_loss_db"]


@needs_p1812
def test_p1812_clutter_increases_loss():
    n = 121
    clutter = np.zeros(n)
    clutter[40:80] = 15.0        # a forest band mid-path (C1 WorldCover style)
    with_c = _p1812_case(clutter=clutter)
    without = _p1812_case()
    assert with_c["clutter_applied"] is True
    assert with_c["path_loss_db"] >= without["path_loss_db"]


@needs_p1812
def test_p1812_rejects_out_of_band():
    with pytest.raises(ValueError):
        _p1812_case(freq=18_000.0)


@needs_p1812
def test_p1812_api_with_worldcover_clutter(fake_store, monkeypatch):
    """C1 x C2 synergy at the API: WorldCover heights feed P.1812's R input."""
    import app.api.routes_terrain as rt
    import app.services.terrain.fusion as fm
    from app.services.terrain.fusion import TerrainFusionService
    from fastapi.testclient import TestClient
    from app.main import app
    import app.services.clutter.worldcover as wc
    from tests.test_clutter import FakeWorldCover
    monkeypatch.setattr(fm, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(rt, "_fusion", TerrainFusionService(store=fake_store))
    monkeypatch.setattr(wc, "_STORE", FakeWorldCover())
    c = TestClient(app)
    common = {"lat1": 47.0, "lon1": 15.0, "lat2": 47.0, "lon2": 15.08,
              "freq_mhz": 900, "h_tx_m": 20, "h_rx_m": 3, "samples": 96}
    bare = c.get("/api/terrain/p1812", params=common).json()
    clut = c.get("/api/terrain/p1812",
                 params={**common, "clutter_source": "worldcover"}).json()
    assert clut["clutter_applied"] is True
    assert clut["path_loss_db"] >= bare["path_loss_db"]
