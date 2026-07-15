"""Tests: per-pixel clutter — WorldCover integration + building footprints."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.clutter.worldcover import (CLASS_TABLE, WorldCoverStore,
                                             clutter_profile_heights,
                                             tile_name)
from app.services.terrain.fusion import TerrainFusionService


class FakeWorldCover(WorldCoverStore):
    """Synthetic world: forest (class 10) between lon 15.02 and 15.04,
    built-up (50) between 15.06 and 15.07, grassland elsewhere."""

    def __init__(self):  # no cache dir / network
        self.heights_by_class = {k: h for k, (_l, h) in CLASS_TABLE.items()}

    def classes(self, lats, lons):
        lons = np.asarray(lons, dtype=np.float64)
        out = np.full(lons.shape, 30, dtype=np.uint8)
        out[(lons >= 15.02) & (lons <= 15.04)] = 10
        out[(lons >= 15.06) & (lons <= 15.07)] = 50
        return out


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    import app.services.clutter.worldcover as wc
    monkeypatch.setattr(wc, "_STORE", FakeWorldCover())
    return TestClient(app)


# ----------------------------------------------------------------- unit
def test_tile_name_grid():
    assert tile_name(47.07, 15.44) == "N45E015"     # Graz -> SW corner N45/E015
    assert tile_name(-1.29, 36.82) == "S03E036"     # Nairobi (southern hemi)
    assert tile_name(40.71, -74.0) == "N39W075"     # New York (western hemi)
    assert tile_name(0.0, 0.0) == "N00E000"


def test_heights_and_terminal_exclusion():
    store = FakeWorldCover()
    lons = np.linspace(15.0, 15.1, 11)
    lats = np.full(11, 47.0)
    h = store.heights(lats, lons)
    assert h[(lons >= 15.02) & (lons <= 15.04)].max() == 15.0   # forest
    assert h[np.isclose(lons, 15.0)].max() == 0.0               # grassland
    hp = clutter_profile_heights(store, lats, lons, terminal_clear=1)
    assert hp[0] == 0.0 and hp[-1] == 0.0                        # terminals free


def test_clutter_obstructs_diffraction():
    """A forest band mid-path must add real diffraction loss."""
    from app.services.rf.models import deygout_loss_db
    d = np.linspace(0, 8000, 201)
    flat = np.full_like(d, 100.0)
    lons = np.linspace(15.0, 15.08, 201)
    store = FakeWorldCover()
    ch = clutter_profile_heights(store, np.full(201, 47.0), lons)
    bare = deygout_loss_db(d, flat, 5.0, 5.0, 900.0)
    cluttered = deygout_loss_db(d, flat + ch, 5.0, 5.0, 900.0)
    assert cluttered > bare + 5.0        # 15 m trees over 5 m antennas: real dB


# ------------------------------------------------------------- API layer
def test_profile_with_worldcover_clutter(client):
    base = client.get("/api/terrain/profile", params={
        "lat1": 47.0, "lon1": 15.0, "lat2": 47.0, "lon2": 15.08,
        "tx_height_m": 5, "rx_height_m": 5, "freq_mhz": 900}).json()
    clut = client.get("/api/terrain/profile", params={
        "lat1": 47.0, "lon1": 15.0, "lat2": 47.0, "lon2": 15.08,
        "tx_height_m": 5, "rx_height_m": 5, "freq_mhz": 900,
        "clutter_source": "worldcover"}).json()
    assert clut["clutter"]["source"] == "esa_worldcover_10m"
    assert clut["clutter"]["max_clutter_height_m"] == 15.0
    # The cluttered path must be at least as obstructed as the bare one.
    assert (clut["rf"]["knife_edge_loss_db"]
            >= base["rf"]["knife_edge_loss_db"])
    assert clut["rf"]["fresnel_clearance_ratio"] \
        <= base["rf"]["fresnel_clearance_ratio"]


def test_profile_rejects_bad_clutter_source(client):
    r = client.get("/api/terrain/profile", params={
        "lat1": 47.0, "lon1": 15.0, "lat2": 47.0, "lon2": 15.05,
        "clutter_source": "landsat"})
    assert r.status_code == 422


def test_coverage_with_worldcover(client):
    body = {"lat": 47.0, "lon": 15.05, "technology": "pmr446",
            "radius_km": 5, "n_radials": 36, "n_steps": 20,
            "clutter_source": "worldcover"}
    r = client.post("/api/rf/coverage", json=body)
    assert r.status_code == 200, r.text
    base = client.post("/api/rf/coverage", json={**body, "clutter_source": "none"})
    # Clutter can only reduce (or keep) the served area.
    assert (r.json()["stats"]["served_area_fraction"]
            <= base.json()["stats"]["served_area_fraction"] + 1e-9)


def test_clutter_status_api(client):
    d = client.get("/api/clutter/status").json()
    assert any(c["code"] == 10 and c["height_m"] == 15.0 for c in d["classes"])


# ------------------------------------------------------ building footprints
def _square(lon0, lat0, dlon, dlat, height=None):
    props = {"height": height} if height is not None else {}
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Polygon", "coordinates": [[
                [lon0, lat0], [lon0 + dlon, lat0], [lon0 + dlon, lat0 + dlat],
                [lon0, lat0 + dlat], [lon0, lat0]]]}}


def test_buildings_to_dsm_extrudes(fake_store):
    from app.services.clutter.buildings import buildings_to_dsm
    fusion = TerrainFusionService(store=fake_store)
    gj = {"type": "FeatureCollection", "features": [
        _square(15.0, 47.0, 0.0005, 0.0005, height=25.0)]}
    grid, georef, stats = buildings_to_dsm(gj, fusion, cell_m=2.0)
    assert stats["buildings"] == 1
    assert stats["max_height_m"] == 25.0
    # Sample the DSM at the building centre: ground + 25 m.
    inside = grid.sample(np.array([15.00025]), np.array([47.00025]))[0]
    ground, _ = fusion.fused_elevations(np.array([47.00025]),
                                        np.array([15.00025]), None, None)
    assert inside == pytest.approx(ground[0] + 25.0, abs=1.0)


def test_buildings_import_api_and_profile_obstruction(client):
    gj = {"type": "FeatureCollection", "features": [
        _square(15.0095, 46.9995, 0.001, 0.001, height=40.0)]}
    up = client.post("/api/clutter/buildings",
                     json={"geojson": gj, "cell_m": 2.0})
    assert up.status_code == 200, up.text
    dsm_id = up.json()["dsm_id"]
    # A low link straight across the 40 m building: surveyed-surface
    # diffraction must exceed bare terrain.
    prof = client.get(f"/api/lidar/{dsm_id}/profile", params={
        "lat1": 47.0, "lon1": 15.0, "lat2": 47.0, "lon2": 15.02,
        "h_tx_m": 3, "h_rx_m": 3, "freq_mhz": 2400, "samples": 128})
    assert prof.status_code == 200, prof.text
    d = prof.json()
    assert d["max_obstruction_m"] > 20.0
    assert d["extra_loss_from_surface_db"] > 0.0


def test_buildings_rejects_empty(client):
    r = client.post("/api/clutter/buildings",
                    json={"geojson": {"type": "FeatureCollection",
                                      "features": []}})
    assert r.status_code == 422
