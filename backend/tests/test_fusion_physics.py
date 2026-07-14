"""Tests for gridding, fusion/feathering, validation and RF physics."""
import numpy as np
import pytest

from app.services.dxf.georef import OriginBearingTransform
from app.services.dxf.gridder import build_grid
from app.services.rf.physics import (analyze_path, apply_earth_curvature,
                                     fresnel_radius_m, knife_edge_loss_db)
from app.services.terrain.fusion import TerrainFusionService


def _planar_points(z0=200.0, sx=0.05, sy=0.02, extent=1000, step=100):
    pts = []
    for x in range(0, extent + 1, step):
        for y in range(0, extent + 1, step):
            pts.append((x, y, z0 + sx * x + sy * y))
    return np.array(pts, dtype=float)


# ---------------------------------------------------------------- gridding
def test_grid_linear_interpolation_accuracy():
    grid = build_grid(_planar_points())
    # A plane must be reproduced almost exactly by linear interpolation.
    v = grid.sample(np.array([437.0]), np.array([612.0]))
    assert v[0] == pytest.approx(200 + 0.05 * 437 + 0.02 * 612, abs=0.05)


def test_grid_nearest_fallback_covers_full_bbox():
    # Sparse scattered points whose convex hull does not reach the bbox corners.
    rng = np.random.default_rng(42)
    pts = np.column_stack([rng.uniform(0, 1000, 40), rng.uniform(0, 1000, 40),
                           rng.uniform(100, 120, 40)])
    grid = build_grid(pts)
    assert not np.isnan(grid.values).any()  # nearest fill leaves no holes


def test_grid_z_scale_feet():
    grid = build_grid(_planar_points(z0=656.17, sx=0, sy=0), z_scale=0.3048)
    v = grid.sample(np.array([500.0]), np.array([500.0]))
    assert v[0] == pytest.approx(200.0, abs=0.1)  # 656.17 ft == 200 m


# ------------------------------------------------------------------ fusion
def _grid_and_georef():
    georef = OriginBearingTransform(origin_lat=47.0, origin_lon=15.0, unit_scale=1.0)
    grid = build_grid(_planar_points(z0=500.0, sx=0.0, sy=0.0))  # flat 500 m slab
    return grid, georef


def test_fusion_dxf_patch_and_feather(fake_store):
    grid, georef = _grid_and_georef()
    fusion = TerrainFusionService(store=fake_store)

    # Deep inside the DXF: pure DXF elevation (weight 1).
    lon_c, lat_c = georef.to_lonlat(np.array([500.0]), np.array([500.0]))
    e, w = fusion.fused_elevations(np.array([lat_c[0]]), np.array([lon_c[0]]),
                                   grid, georef)
    assert w[0] == pytest.approx(1.0)
    assert e[0] == pytest.approx(500.0, abs=0.5)

    # Far outside: pure SRTM (the fake ramp world, ~100-600 m), weight 0.
    e_out, w_out = fusion.fused_elevations(np.array([47.5]), np.array([16.0]),
                                           grid, georef)
    assert w_out[0] == 0.0

    # Within the 3-cell feather band: strictly between the two surfaces.
    lon_e, lat_e = georef.to_lonlat(np.array([grid.x0 + grid.dx * 1.5]),
                                    np.array([500.0]))
    e_b, w_b = fusion.fused_elevations(np.array([lat_e[0]]), np.array([lon_e[0]]),
                                       grid, georef)
    assert 0.0 < w_b[0] < 1.0


def test_fusion_profile_provenance_labels(fake_store):
    grid, georef = _grid_and_georef()
    fusion = TerrainFusionService(store=fake_store)
    # Path crossing the DXF: start ~2.2 km west of the site, end inside it.
    lon_a, lat_a = georef.to_lonlat(np.array([-2200.0]), np.array([500.0]))
    lon_b, lat_b = georef.to_lonlat(np.array([800.0]), np.array([500.0]))
    prof = fusion.profile(float(lat_a[0]), float(lon_a[0]),
                          float(lat_b[0]), float(lon_b[0]),
                          n_samples=128, grid=grid, georef=georef)
    srcs = set(prof.source)
    assert "srtm" in srcs and "dxf" in srcs  # both provenances present
    # Fused surface never NaN.
    assert not np.isnan(prof.elevations_m).any()
    # Feather: no step larger than ~the SRTM/DXF gap between adjacent samples.
    steps = np.abs(np.diff(prof.elevations_m))
    assert steps.max() < 150.0


def test_validation_warns_on_unit_mismatch(fake_store):
    georef = OriginBearingTransform(origin_lat=47.0, origin_lon=15.0)
    fusion = TerrainFusionService(store=fake_store)
    # Fake-world SRTM near lon 15 is ~370 m; a 500 m DXF slab is within 50 m?
    # No: |500-370| = ~130 -> warning expected.
    grid_bad = build_grid(_planar_points(z0=500.0, sx=0, sy=0))
    v = fusion.validate_against_srtm(grid_bad, georef)
    assert v["warning"] is not None
    # A slab matching the local SRTM mean passes.
    srtm_local = fake_store.elevation_at(15.0, 47.0)
    grid_ok = build_grid(_planar_points(z0=srtm_local, sx=0, sy=0))
    v_ok = fusion.validate_against_srtm(grid_ok, georef)
    assert v_ok["warning"] is None
    assert v_ok["mean_diff_m"] == pytest.approx(0.0, abs=5.0)


# --------------------------------------------------------------- physics
def test_earth_curvature_bulge():
    d = np.linspace(0, 50_000, 101)  # 50 km path
    e = np.zeros_like(d)
    curved = apply_earth_curvature(d, e, k=4.0 / 3.0)
    # Midpath bulge for 50 km, k=4/3: d1*d2/(2kR) = 25e3^2/(2*4/3*6371e3) ~= 36.8 m
    assert curved[50] == pytest.approx(36.8, abs=0.5)
    assert curved[0] == pytest.approx(0.0)
    assert curved[-1] == pytest.approx(0.0)


def test_fresnel_radius():
    # 1 GHz, midpoint of a 10 km path: sqrt(lam*d1*d2/D) = sqrt(0.3*5e3*5e3/1e4) ~= 27.4
    r = fresnel_radius_m(np.array([5000.0]), np.array([5000.0]), 1e9)
    assert r[0] == pytest.approx(27.4, abs=0.2)


def test_knife_edge_loss():
    assert knife_edge_loss_db(-1.0) == 0.0
    assert knife_edge_loss_db(0.0) == pytest.approx(6.0, abs=1.0)   # grazing ~6 dB
    assert knife_edge_loss_db(2.0) > 15.0


def test_analyze_path_obstructed_vs_clear():
    d = np.linspace(0, 20_000, 201)
    flat = np.full_like(d, 100.0)
    hill = flat.copy()
    hill[95:105] = 260.0  # 160 m obstacle mid-path

    clear = analyze_path(d, flat, tx_height_m=30, rx_height_m=30, freq_mhz=446)
    blocked = analyze_path(d, hill, tx_height_m=30, rx_height_m=30, freq_mhz=446)

    assert clear["line_of_sight_clear"]
    assert not blocked["line_of_sight_clear"]
    assert blocked["knife_edge_loss_db"] > 10.0
    # Curvature applied: interior curved terrain sits above raw terrain.
    assert (clear["terrain_curved_m"][1:-1] > flat[1:-1]).all()
