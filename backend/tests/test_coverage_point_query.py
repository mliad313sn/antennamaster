"""Point-value inspection of a coverage study.

A raster shows the class of every pixel but not its value. `/at` reports the
predicted level at a location so a planner can read the actual dBm at a
candidate address without re-running a study.

The invariant that matters: the number reported MUST be the number that
painted the pixel. If they could disagree the feature is worse than useless -
it would quietly contradict the map.
"""
import io

import numpy as np
import pytest
from PIL import Image

from fastapi.testclient import TestClient

from app.api import routes_terrain
from app.main import app
from app.services.rf.technologies import get_technology
from app.services.terrain import fusion as fusion_mod
from app.services.terrain.coverage import (LEGEND_STEPS, CoverageEngine,
                                           classify_margin, point_value)
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch, tmp_path):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


@pytest.fixture
def study(fake_store):
    engine = CoverageEngine(TerrainFusionService(store=fake_store))
    res = engine.simulate(47.0, 15.0, get_technology("gsm900"),
                          radius_m=6000.0, n_radials=72, n_steps=60,
                          raster_px=256)
    return res


def test_point_value_matches_the_painted_pixel(study):
    """Sample the raster and the point query at the same coordinates and
    require the colour to match the reported grade - everywhere."""
    (south, west), (north, east) = study.bounds
    img = np.array(Image.open(io.BytesIO(study.png)).convert("RGBA"))
    px = img.shape[0]
    lat_g = np.linspace(north, south, px)      # row 0 = north, as rasterized
    lon_g = np.linspace(west, east, px)

    checked = 0
    for row in range(5, px, 37):                # deterministic spread of samples
        for col in range(5, px, 37):
            lat, lon = float(lat_g[row]), float(lon_g[col])
            got = point_value(
                study.polar["az"], study.polar["dist"], study.polar["margin"],
                study.polar["rx_power"], tx_lat=47.0, tx_lon=15.0,
                radius_m=6000.0, lat=lat, lon=lon)
            r, g, b, a = (int(v) for v in img[row, col])
            if not got.get("inside"):
                assert a == 0, "outside the radius the raster must be transparent"
                continue
            grade = got["grade"]
            if a == 0:
                # Transparent inside the disc == unserved; the value must agree.
                assert grade is None and got["margin_db"] < 0.0
            else:
                assert grade is not None, "painted pixel must have a grade"
                assert grade["color"] == "#%02x%02x%02x" % (r, g, b), (
                    f"value/colour disagree at {lat:.4f},{lon:.4f}")
                checked += 1
    assert checked > 20, "sampled too few painted pixels to be meaningful"


def test_point_at_transmitter_is_the_strongest_sample(study):
    """The site itself must be served and at least as strong as anywhere else."""
    at_tx = point_value(
        study.polar["az"], study.polar["dist"], study.polar["margin"],
        study.polar["rx_power"], tx_lat=47.0, tx_lon=15.0,
        radius_m=6000.0, lat=47.0, lon=15.0)
    assert at_tx["inside"] and at_tx["served"]
    assert at_tx["rx_power_dbm"] == pytest.approx(
        study.stats["max_rx_power_dbm"], abs=0.15)
    assert at_tx["distance_m"] < 100.0


def test_outside_the_radius_reports_not_inside(study):
    far = point_value(
        study.polar["az"], study.polar["dist"], study.polar["margin"],
        study.polar["rx_power"], tx_lat=47.0, tx_lon=15.0,
        radius_m=6000.0, lat=47.5, lon=15.0)          # ~55 km north
    assert far["inside"] is False
    assert far["distance_m"] > 6000.0


def test_bearing_is_measured_clockwise_from_north(study):
    """Bearing must follow the geodesic convention the sweep used, or the
    reported azimuth would point at a different radial than the one sampled."""
    args = (study.polar["az"], study.polar["dist"], study.polar["margin"],
            study.polar["rx_power"])
    north = point_value(*args, tx_lat=47.0, tx_lon=15.0, radius_m=6000.0,
                        lat=47.02, lon=15.0)
    east = point_value(*args, tx_lat=47.0, tx_lon=15.0, radius_m=6000.0,
                       lat=47.0, lon=15.03)
    assert north["bearing_deg"] == pytest.approx(0.0, abs=1.0)
    assert east["bearing_deg"] == pytest.approx(90.0, abs=1.0)


def test_classify_margin_boundaries():
    top = LEGEND_STEPS[0][0]
    assert classify_margin(top)["margin_db"] == top          # inclusive bound
    assert classify_margin(top + 5)["margin_db"] == top
    assert classify_margin(0.0)["margin_db"] == 0.0          # marginal, served
    assert classify_margin(-0.1) is None                     # unserved


def test_at_endpoint_round_trip(client):
    """End to end through the API: run a study, then inspect a point in it."""
    r = client.post("/api/rf/coverage", json={
        "lat": 47.0, "lon": 15.0, "technology": "gsm900", "radius_km": 5,
        "n_radials": 36, "n_steps": 30, "raster_px": 128})
    assert r.status_code == 200
    cid = r.json()["coverage_id"]

    at = client.get(f"/api/rf/coverage/{cid}/at",
                    params={"lat": 47.0, "lon": 15.0})
    assert at.status_code == 200
    body = at.json()
    assert body["inside"] and body["served"]
    assert body["rx_power_dbm"] == pytest.approx(
        r.json()["stats"]["max_rx_power_dbm"], abs=0.15)

    outside = client.get(f"/api/rf/coverage/{cid}/at",
                         params={"lat": 48.0, "lon": 15.0})
    assert outside.status_code == 200 and outside.json()["inside"] is False

    assert client.get("/api/rf/coverage/deadbeef/at",
                      params={"lat": 47.0, "lon": 15.0}).status_code == 404
