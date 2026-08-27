"""ITU-R P.1812 as an area-coverage engine.

Why alongside the ITM area engine rather than instead of it: ITM is what the
incumbent planning tools run, so a study made with it can be checked by a
reviewer in their own tool; P.1812 is what a European regulator's own
coordination is based on, so a study made with it is checkable against the
Recommendation itself. A consultant wants both, and wants to be told which
one produced a given number.

TWO TIERS OF TEST, deliberately separated.

The *numerical* correctness of P.1812 is the official reference
implementation's business, and it is proven in `test_itu_validation.py`
against the published validation profiles. Those tests need the ITU digital
refractivity maps, which are ITU integral products and are not redistributed
here; CI installs them and FAILS if the validation tests skip.

What this file proves is the part we wrote: that the fan is assembled from
the official call correctly, that clutter goes in as the Recommendation's own
input rather than being added to the ground twice, that no diffraction term
is stacked on top, and that the range limit is respected. Those are
structural claims, so they are asserted against a recorded stand-in for the
official call and hold whether or not the maps are installed.
"""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.routes_rf as routes_rf
import app.api.routes_terrain as routes_terrain
import app.services.rf.itm_exact as itm_exact
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.rf.itm_exact import P1812_MIN_RANGE_M, p1812_available
from app.services.rf.models import MODEL_INFO, fspl_db
from app.services.terrain.fusion import TerrainFusionService

needs_itu_maps = pytest.mark.skipif(
    not p1812_available(),
    reason="ITU digital maps not installed (integral ITU products); CI "
           "installs them and fails if the validation tests skip")


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    fusion = TerrainFusionService(store=fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion", fusion)
    monkeypatch.setattr(routes_rf, "resolve_fusion", lambda surface=False: fusion)
    return TestClient(app)


@pytest.fixture
def recorded(monkeypatch):
    """Stand in for the official call and record exactly what it was given.

    The point of the substitution is not to fake physics — it is that the
    arguments handed to the Recommendation ARE the thing under test here.
    """
    calls: list[dict] = []

    def fake(distances_m, elevations_m, lats, lons, h_tx_m, h_rx_m, freq_mhz,
             time_pct=50.0, location_pct=50.0, clutter_heights_m=None,
             polarization=1):
        calls.append({
            "d": np.asarray(distances_m, dtype=float),
            "h": np.asarray(elevations_m, dtype=float),
            "lat": np.asarray(lats, dtype=float),
            "lon": np.asarray(lons, dtype=float),
            "R": None if clutter_heights_m is None
                 else np.asarray(clutter_heights_m, dtype=float),
            "time_pct": time_pct, "location_pct": location_pct,
        })
        # A monotone stand-in: loss grows with range and with pL, so the
        # engine's plumbing of both is observable.
        span_km = max(float(np.asarray(distances_m)[-1]) / 1000.0, 0.01)
        return {"path_loss_db": 100.0 + 20.0 * np.log10(span_km)
                                + 0.2 * (location_pct - 50.0)}

    monkeypatch.setattr(itm_exact, "p1812_loss", fake)
    # The fixture substitutes the official call, so it must substitute its
    # availability too — otherwise the API's "maps not installed" guard
    # (correctly) refuses the study before the stand-in is ever reached.
    monkeypatch.setattr(itm_exact, "p1812_available", lambda: True)
    return calls


def _fan(radials=3, steps=20, radius_m=8000.0):
    dist = np.linspace(radius_m / steps, radius_m, steps)
    ridge = 200.0 + 90.0 * np.exp(-((dist - 4000.0) / 1200.0) ** 2)
    elev = np.tile(ridge, (radials, 1))
    lats = np.tile(47.0 + dist / 111_000.0, (radials, 1))
    lons = np.full_like(elev, 15.0)
    return elev, dist, lats, lons


# ------------------------------------------------------ what we assembled
def test_every_profile_starts_at_the_mast(recorded):
    """The Recommendation places its horizon from the transmitter's own
    ground height and position. The sweep's samples begin one step out, so a
    profile that started at the first sample would put the mast on the wrong
    hill."""
    elev, dist, lats, lons = _fan()
    itm_exact.p1812_loss_grid(elev, dist, lats, lons, 47.0, 15.0, 210.0,
                              30.0, 1.5, 450.0)
    assert recorded, "the official engine was never called"
    for call in recorded:
        assert call["d"][0] == 0.0
        assert call["h"][0] == 210.0
        assert call["lat"][0] == 47.0 and call["lon"][0] == 15.0


def test_clutter_goes_in_as_the_recommendations_own_input(recorded):
    """The trap. Our Deygout path legitimately raises the obstacle surface by
    the canopy height; P.1812 takes representative clutter as a separate R
    array next to BARE ground. Doing both would apply the same trees twice.
    """
    elev, dist, lats, lons = _fan()
    canopy = np.full_like(elev, 12.0)
    _, warnings = itm_exact.p1812_loss_grid(
        elev, dist, lats, lons, 47.0, 15.0, 210.0, 30.0, 1.5, 450.0,
        clutter_heights=canopy)

    call = recorded[-1]
    assert call["R"] is not None
    assert np.allclose(call["R"][1:], 12.0)
    # The ground handed over is bare: the canopy is NOT in h as well.
    assert np.allclose(call["h"][1:], elev[-1][: call["h"].size - 1])
    assert any("representative-height input R" in w for w in warnings)


def test_the_time_and_location_percentages_are_both_forwarded(recorded):
    """P.1812's pair is what a coverage obligation is written in — "the level
    exceeded at 95% of locations, 50% of the time". A knob that is accepted
    and dropped would be worse than one that does not exist."""
    elev, dist, lats, lons = _fan()
    itm_exact.p1812_loss_grid(elev, dist, lats, lons, 47.0, 15.0, 210.0,
                              30.0, 1.5, 450.0, time_pct=10.0,
                              location_pct=95.0)
    assert all(c["time_pct"] == 10.0 for c in recorded)
    assert all(c["location_pct"] == 95.0 for c in recorded)


def test_a_stricter_location_percentage_is_never_optimistic(recorded):
    elev, dist, lats, lons = _fan()
    median, _ = itm_exact.p1812_loss_grid(elev, dist, lats, lons, 47.0, 15.0,
                                          210.0, 30.0, 1.5, 450.0,
                                          location_pct=50.0)
    strict, _ = itm_exact.p1812_loss_grid(elev, dist, lats, lons, 47.0, 15.0,
                                          210.0, 30.0, 1.5, 450.0,
                                          location_pct=95.0)
    far = dist >= P1812_MIN_RANGE_M
    assert np.all(strict[:, far] >= median[:, far] - 1e-9)


def test_below_250_m_it_says_free_space_instead_of_extrapolating(recorded):
    """P.1812 is defined from 250 m. Running the official code outside its
    own stated range and painting the result over the busiest part of the map
    is exactly the kind of quiet extrapolation this project refuses."""
    elev, dist, lats, lons = _fan(steps=40, radius_m=8000.0)
    grid, warnings = itm_exact.p1812_loss_grid(
        elev, dist, lats, lons, 47.0, 15.0, 210.0, 30.0, 1.5, 450.0)
    near = dist < P1812_MIN_RANGE_M
    assert near.any(), "the fixture should include samples inside 250 m"
    assert np.allclose(grid[0, near], fspl_db(dist[near], 450.0))
    assert any("free space" in w for w in warnings)
    assert all(c["d"][-1] >= P1812_MIN_RANGE_M for c in recorded)


def test_out_of_band_is_refused_with_the_alternative_named():
    """30 MHz - 6 GHz. A 24 GHz preset must not quietly get a P.1812 number."""
    elev, dist, lats, lons = _fan()
    with pytest.raises(ValueError, match="30 MHz - 6 GHz"):
        itm_exact.p1812_loss_grid(elev, dist, lats, lons, 47.0, 15.0, 210.0,
                                  30.0, 1.5, 24_000.0)


# ------------------------------------------------------------ the study
def test_terrain_is_not_counted_twice_in_a_study(client, recorded):
    """P.1812 derives the terrain effect itself, so the sweep must add no
    Deygout term. Stacking both would look plausible — coverage behind a
    ridge IS poor — and be tens of dB wrong."""
    body = {"lat": 47.0, "lon": 15.0, "technology": "pmr446", "radius_km": 6,
            "n_radials": 36, "n_steps": 30, "resolution_m": 400}
    hata = client.post("/api/rf/coverage",
                       json={**body, "model": "okumura_hata"})
    p1812 = client.post("/api/rf/coverage", json={**body, "model": "p1812"})
    assert hata.status_code == 200, hata.text
    assert p1812.status_code == 200, p1812.text

    a = hata.json()["stats"]["max_rx_power_dbm"]
    b = p1812.json()["stats"]["max_rx_power_dbm"]
    assert abs(a - b) < 40.0, f"hata {a} dBm vs p1812 {b} dBm — counted twice?"


def test_the_quantiles_reach_the_engine_from_the_request(client, recorded):
    body = {"lat": 47.0, "lon": 15.0, "technology": "pmr446", "radius_km": 6,
            "n_radials": 36, "n_steps": 30, "resolution_m": 400,
            "model": "p1812", "p1812_time_pct": 10.0,
            "p1812_location_pct": 95.0}
    r = client.post("/api/rf/coverage", json=body)
    assert r.status_code == 200, r.text
    echoed = r.json()["technology"]
    assert echoed["p1812_time_pct"] == 10.0
    assert echoed["p1812_location_pct"] == 95.0
    assert recorded and recorded[-1]["location_pct"] == 95.0
    # ...and the filed study records which engine and which percentages ran.
    rec = client.get(f"/api/rf/coverage/{r.json()['coverage_id']}/record")
    assert rec.json()["request"]["p1812_location_pct"] == 95.0


def test_it_is_offered_in_the_model_list_with_its_real_validity(client):
    models = {m["key"]: m for m in client.get("/api/rf/models").json()["models"]}
    assert "p1812" in models
    assert models["p1812"]["f_range_mhz"] == [30.0, 6_000.0]
    # No environments: the terrain and the clutter input ARE the environment,
    # and an urban/suburban dropdown beside it would imply a dead knob.
    assert models["p1812"]["environments"] == []
    assert "P.1812" in MODEL_INFO["p1812"]["label"]


def test_a_deployment_without_the_itu_maps_says_so_and_names_the_fix(
        client, monkeypatch):
    """The maps are ITU integral products and are not redistributed, so a
    self-hosted install may legitimately not have them. A stack trace out of
    a third-party import would be useless, and quietly substituting another
    model for the one asked for — on a study someone will file — would be
    worse than useless."""
    monkeypatch.setattr(routes_rf, "p1812_available", lambda: False,
                        raising=False)
    monkeypatch.setattr("app.services.rf.itm_exact.p1812_available",
                        lambda: False)
    r = client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "pmr446", "radius_km": 4,
        "n_radials": 36, "n_steps": 20, "resolution_m": 400,
        "model": "p1812"})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "fetch_itu_maps" in detail
    assert 'model="itm"' in detail          # a usable alternative, named


# ------------------------------------------------- real engine, when present
@needs_itu_maps
def test_the_grid_agrees_with_the_official_point_to_point_call():
    """Same algorithm, not a re-derivation: a coverage plot that disagreed
    with the link study of the same path is what makes a planner stop
    trusting a tool. Runs only where the ITU maps are installed."""
    from app.services.rf.itm_exact import p1812_loss
    elev, dist, lats, lons = _fan(radials=1, steps=20)
    grid, _ = itm_exact.p1812_loss_grid(elev, dist, lats, lons, 47.0, 15.0,
                                        210.0, 30.0, 1.5, 450.0)
    last = elev.shape[1] - 1
    d_ray = np.concatenate(([0.0], dist))
    h_ray = np.concatenate(([210.0], elev[0]))
    lat_ray = np.concatenate(([47.0], lats[0]))
    lon_ray = np.concatenate(([15.0], lons[0]))
    ref = p1812_loss(d_ray[: last + 2], h_ray[: last + 2],
                     lat_ray[: last + 2], lon_ray[: last + 2],
                     30.0, 1.5, 450.0)
    assert grid[0, last] == pytest.approx(ref["path_loss_db"], abs=1e-9)


@needs_itu_maps
def test_a_real_study_is_physically_sane():
    """Loss grows with range and never beats free space. Cheap, but it is the
    check that catches a mis-assembled profile reaching the official code."""
    elev, dist, lats, lons = _fan(radials=2, steps=24, radius_m=10_000.0)
    grid, _ = itm_exact.p1812_loss_grid(elev, dist, lats, lons, 47.0, 15.0,
                                        210.0, 30.0, 1.5, 450.0)
    far = dist >= P1812_MIN_RANGE_M
    assert np.all(grid[:, far] >= fspl_db(dist[far], 450.0) - 0.5)
    assert grid[0, -1] > grid[0, np.argmax(far)]
