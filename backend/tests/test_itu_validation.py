"""CI gates: this installation reproduces the OFFICIAL ITU-R validation
examples for P.452-18 and P.2001 at the reference tolerance (1e-6 dB).

These are the same anchors `tools/validate_predictions.py` prints into
PRECISION_BENCHMARK.md — exactness as an executable claim, not a brochure
sentence.  Fixtures + attribution: `benchmarks/validation/README.md`.
"""
import numpy as np
import pytest

from tools.validate_predictions import p2001_validation, p452_validation

TOL_DB = 1e-6


def test_p452_official_validation_examples():
    v = p452_validation()
    if v is None:
        pytest.skip("Py452 / ITU digital maps not installed")
    assert v["cases"] >= 30
    assert v["worst_deviation_db"] <= TOL_DB, v


def test_p2001_official_validation_examples():
    v = p2001_validation()
    if v is None:
        pytest.skip("Py2001 / ITU digital maps not installed")
    assert v["cases"] >= 40
    assert v["worst_deviation_db"] <= TOL_DB, v


# ------------------------------------------------ P.2001 engine behaviour
needs_p2001 = pytest.mark.skipif(
    not pytest.importorskip("app.services.rf.itm_exact").p2001_available(),
    reason="Py2001 / ITU digital maps not installed")


@needs_p2001
def test_p2001_full_time_range_is_monotonic():
    """The wide-range model spans 0-100 % of the year in one prediction:
    loss not exceeded for a larger fraction of the year must be larger."""
    from app.services.rf.itm_exact import p2001_loss
    n = 300
    d = np.linspace(0.0, 100_000.0, n)
    h = np.full(n, 300.0)
    lats = np.linspace(46.5, 47.4, n)
    lons = np.full(n, 15.0)
    losses = [p2001_loss(d, h, lats, lons, 30, 30, 600.0, time_pct=p)
              ["path_loss_db"] for p in (0.01, 1.0, 50.0, 99.0, 99.99)]
    assert losses == sorted(losses), losses
    with pytest.raises(ValueError):
        p2001_loss(d, h, lats, lons, 30, 30, 20.0)      # 20 MHz < 30 MHz


@needs_p2001
def test_p2001_api_route(fake_store, monkeypatch):
    import app.api.routes_terrain as routes_terrain
    import app.services.terrain.fusion as fusion_mod
    from app.main import app
    from app.services.terrain.fusion import TerrainFusionService
    from fastapi.testclient import TestClient
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    client = TestClient(app)
    r = client.get("/api/terrain/p2001", params={
        "lat1": 47.0, "lon1": 15.0, "lat2": 47.5, "lon2": 15.8,
        "freq_mhz": 600, "time_pct": 50})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["engine"] == "itu_p2001_official"
    assert d["path_loss_db"] > 100
