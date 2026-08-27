"""ITM as an area-coverage engine, not just a link tool.

The empirical models the sweep offered (Hata, COST-231, TR 38.901) are fitted
curves plus our own Deygout diffraction. ITM/Longley-Rice is the algorithm
regulators and the incumbent tools — SPLAT!, Radio Mobile, TAP — actually run,
and a consultant's study is defensible partly because a reviewer can
reproduce it in their own tool. It existed here only point-to-point.

The trap this suite guards is double-counting: ITM derives the terrain effect
itself, so the sweep must not add Deygout on top of it.
"""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.routes_rf as routes_rf
import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.rf.itm_exact import ITM_MIN_RANGE_M, itm_loss_grid, itm_p2p_loss
from app.services.rf.models import MODEL_INFO, fspl_db
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    fusion = TerrainFusionService(store=fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion", fusion)
    monkeypatch.setattr(routes_rf, "resolve_fusion", lambda surface=False: fusion)
    return TestClient(app)


def _ramp(radials=8, steps=40, radius_m=12_000.0):
    """A ridge crossing every ray, so terrain actually matters."""
    dist = np.linspace(radius_m / steps, radius_m, steps)
    ridge = 200.0 + 120.0 * np.exp(-((dist - 6000.0) / 1500.0) ** 2)
    return np.tile(ridge, (radials, 1)), dist


def test_the_grid_agrees_exactly_with_the_point_to_point_engine():
    """The area engine must be the *same* algorithm, not a re-derivation.

    Anything else and a coverage plot would disagree with the link study of
    the same path, which is precisely the inconsistency that makes a planner
    stop trusting a tool.
    """
    elev, dist = _ramp(radials=1, steps=40)
    grid, _ = itm_loss_grid(elev, dist, 200.0, 30.0, 2.0, 450.0)

    last = elev.shape[1] - 1
    d_ray = np.concatenate(([0.0], dist))
    e_ray = np.concatenate(([200.0], elev[0]))
    ref = itm_p2p_loss(d_ray[: last + 2], e_ray[: last + 2], 30.0, 2.0, 450.0)
    assert grid[0, last] == pytest.approx(ref["path_loss_db"], abs=1e-9)


def test_terrain_is_counted_once_not_twice(client):
    """The whole risk of bolting ITM onto a sweep that already has Deygout.

    A study that added both would be tens of dB pessimistic behind every
    ridge — and would look plausible, because coverage behind a ridge *is*
    poor. Comparing the two engines on the same terrain is what catches it:
    ITM must land near the empirical+Deygout answer, not far below it.
    """
    body = {"lat": 47.0, "lon": 15.0, "technology": "pmr446", "radius_km": 8,
            "n_radials": 36, "n_steps": 40, "resolution_m": 400}
    hata = client.post("/api/rf/coverage",
                       json={**body, "model": "okumura_hata"})
    itm = client.post("/api/rf/coverage", json={**body, "model": "itm"})
    assert hata.status_code == 200, hata.text
    assert itm.status_code == 200, itm.text

    a = hata.json()["stats"]["max_rx_power_dbm"]
    b = itm.json()["stats"]["max_rx_power_dbm"]
    # Two different models, so not equal - but the same physical situation.
    # A double-counted diffraction term would push ITM far below this band.
    assert abs(a - b) < 40.0, f"hata {a} dBm vs itm {b} dBm — terrain counted twice?"


def test_a_higher_reliability_quantile_is_never_optimistic():
    """ITM's reason to exist over an empirical curve: it answers "the level
    exceeded at X% of locations, Y% of the time", which is the number a
    licence application or an SLA is written on. A 90% study must therefore
    predict *less* signal than a 50% one, never more."""
    elev, dist = _ramp()
    median, _ = itm_loss_grid(elev, dist, 200.0, 30.0, 2.0, 450.0,
                              reliability_pct=50.0)
    strict, _ = itm_loss_grid(elev, dist, 200.0, 30.0, 2.0, 450.0,
                              reliability_pct=90.0)
    far = dist >= ITM_MIN_RANGE_M
    assert np.all(strict[:, far] >= median[:, far] - 1e-9)
    assert strict[:, far].mean() > median[:, far].mean() + 1.0


def test_below_its_stated_range_it_says_so_instead_of_guessing():
    """ITM is specified from 1 km and sets its own out-of-range flag below
    that rather than refusing — which would have silently painted an
    unsupported number over the busiest part of the map."""
    elev, dist = _ramp(steps=40, radius_m=12_000.0)
    grid, warnings = itm_loss_grid(elev, dist, 200.0, 30.0, 2.0, 450.0)
    near = dist < ITM_MIN_RANGE_M
    assert near.any(), "the fixture should include samples inside 1 km"
    assert np.allclose(grid[0, near], fspl_db(dist[near], 450.0))
    assert any("free space" in w for w in warnings)


def test_it_is_offered_in_the_model_list_with_its_real_validity(client):
    models = {m["key"]: m for m in client.get("/api/rf/models").json()["models"]}
    assert "itm" in models, "the engine is unusable if the picker never offers it"
    assert models["itm"]["f_range_mhz"] == [20.0, 20_000.0]
    # No environments: with ITM the terrain *is* the environment, and an
    # urban/suburban dropdown next to it would imply a knob that does nothing.
    assert models["itm"]["environments"] == []
    assert MODEL_INFO["itm"]["label"].startswith("ITM")


def test_the_quantiles_reach_the_engine_from_the_request(client):
    """A knob that is accepted but ignored is worse than one that is missing.

    Asserted on the echo rather than on a level, deliberately: the fixture
    terrain is a smooth ramp, so ITM's terrain-irregularity term dh is
    near zero and location variability with it — the 95% study genuinely
    lands within 0.1 dB of the median there, which is the model being right,
    not the knob being dead. The magnitude is asserted in
    `test_a_higher_reliability_quantile_is_never_optimistic`, over terrain
    rough enough to produce one.
    """
    body = {"lat": 47.0, "lon": 15.0, "technology": "pmr446", "radius_km": 8,
            "n_radials": 36, "n_steps": 40, "resolution_m": 400, "model": "itm"}
    r = client.post("/api/rf/coverage", json={**body, "itm_reliability_pct": 95.0})
    assert r.status_code == 200, r.text
    echoed = r.json()["technology"]
    assert echoed["itm_reliability_pct"] == 95.0
    assert echoed["itm_confidence_pct"] == 50.0
    assert echoed["model"] == "itm"


def test_a_smooth_ramp_is_not_evidence_that_the_quantile_works(client):
    """Guard the guard: if the fixture terrain ever gains real roughness,
    the API-level test above should start seeing a difference, and this
    records why it does not today."""
    body = {"lat": 47.0, "lon": 15.0, "technology": "pmr446", "radius_km": 8,
            "n_radials": 36, "n_steps": 40, "resolution_m": 400, "model": "itm"}
    far = {"lat": 47.045, "lon": 15.0}

    def level_at(reliability):
        r = client.post("/api/rf/coverage",
                        json={**body, "itm_reliability_pct": reliability})
        cid = r.json()["coverage_id"]
        return client.get(f"/api/rf/coverage/{cid}/at", params=far
                          ).json()["rx_power_dbm"]

    # Never optimistic, whatever the terrain.
    assert level_at(95.0) <= level_at(50.0) + 1e-9
