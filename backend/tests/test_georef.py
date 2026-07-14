"""Unit tests for the three georeferencing modes and the DXF parser."""
import math

import numpy as np
import pytest

from app.services.dxf.georef import (ControlPoint, HelmertTransform,
                                     KnownCrsTransform, OriginBearingTransform,
                                     build_georef)
from app.services.dxf.parser import extract_points, list_layers, load_dxf


# --------------------------------------------------------------- mode A
def test_known_crs_roundtrip():
    # UTM zone 33N, a point near Vienna.
    tr = KnownCrsTransform("EPSG:32633")
    lon, lat = tr.to_lonlat(np.array([602000.0]), np.array([5340000.0]))
    assert 16.0 < lon[0] < 16.6
    assert 48.1 < lat[0] < 48.4
    x, y = tr.from_lonlat(lon, lat)
    assert abs(x[0] - 602000.0) < 0.01
    assert abs(y[0] - 5340000.0) < 0.01
    assert tr.meters_per_unit() == pytest.approx(1.0)


# --------------------------------------------------------------- mode B
def test_helmert_recovers_known_transform():
    """Fabricate a ground truth transform, generate control points from it,
    and check the solver recovers scale/rotation with ~zero residuals."""
    truth = OriginBearingTransform(origin_lat=47.0, origin_lon=15.0,
                                   bearing_deg=30.0, unit_scale=2.0)
    cps = []
    for x, y in ((0, 0), (1000, 0), (0, 800)):
        lon, lat = truth.to_lonlat(np.array([x]), np.array([y]))
        cps.append(ControlPoint(dxf_x=x, dxf_y=y, lat=float(lat[0]), lon=float(lon[0])))

    solved = HelmertTransform(cps)
    assert solved.scale == pytest.approx(2.0, rel=1e-3)
    # Bearing 30 deg (Y axis rotated CW toward east) == math rotation -30 deg.
    assert solved.rotation_deg == pytest.approx(-30.0, abs=0.1)
    assert solved.rms_residual_m < 0.5

    # Round-trip an arbitrary interior point through solved vs truth.
    lon_t, lat_t = truth.to_lonlat(np.array([432.0]), np.array([567.0]))
    lon_s, lat_s = solved.to_lonlat(np.array([432.0]), np.array([567.0]))
    assert abs(lon_t[0] - lon_s[0]) < 1e-5
    assert abs(lat_t[0] - lat_s[0]) < 1e-5


def test_helmert_two_points_and_residual_reporting():
    truth = OriginBearingTransform(origin_lat=-33.9, origin_lon=18.4,
                                   bearing_deg=0.0, unit_scale=1.0)
    cps = []
    for x, y in ((100, 100), (900, 700)):
        lon, lat = truth.to_lonlat(np.array([x]), np.array([y]))
        cps.append(ControlPoint(dxf_x=x, dxf_y=y, lat=float(lat[0]), lon=float(lon[0])))
    solved = HelmertTransform(cps)
    # 2 points -> 4 equations, 4 unknowns: exact fit.
    assert solved.rms_residual_m < 0.01
    assert len(solved.residuals_m) == 2


def test_helmert_rejects_bad_point_counts():
    cp = ControlPoint(0, 0, 47.0, 15.0)
    with pytest.raises(ValueError):
        HelmertTransform([cp])
    with pytest.raises(ValueError):
        HelmertTransform([cp] * 4)


# --------------------------------------------------------------- mode C
def test_origin_bearing_geometry():
    tr = OriginBearingTransform(origin_lat=50.0, origin_lon=8.0,
                                bearing_deg=90.0, unit_scale=1.0)
    # +Y in the DXF points due east (bearing 90): 1000 units up => 1 km east.
    lon, lat = tr.to_lonlat(np.array([0.0]), np.array([1000.0]))
    assert lat[0] == pytest.approx(50.0, abs=1e-4)
    assert lon[0] > 8.0
    # Round trip.
    x, y = tr.from_lonlat(lon, lat)
    assert x[0] == pytest.approx(0.0, abs=0.01)
    assert y[0] == pytest.approx(1000.0, abs=0.01)


def test_origin_bearing_feet_scale():
    tr = OriginBearingTransform(origin_lat=40.0, origin_lon=-105.0,
                                unit_scale=0.3048)  # drawing in feet
    lon, lat = tr.to_lonlat(np.array([0.0]), np.array([1000.0]))  # 1000 ft north
    x, y = tr.from_lonlat(lon, lat)
    assert y[0] == pytest.approx(1000.0, abs=0.1)
    assert tr.z_scale == pytest.approx(0.3048)  # vertical follows horizontal


def test_build_georef_dispatch():
    assert build_georef({"mode": "known_crs", "crs": "EPSG:32633"}).describe()["mode"] == "known_crs"
    with pytest.raises(ValueError):
        build_georef({"mode": "nope"})


# --------------------------------------------------------------- parser
def test_parser_layers_and_points(site_dxf):
    doc = load_dxf(str(site_dxf))
    layers = {l["name"]: l for l in list_layers(doc)}
    assert layers["SURVEY_POINTS"]["looks_like_terrain"]
    assert layers["CONTOURS"]["looks_like_terrain"]
    assert "LWPOLYLINE" in layers["CONTOURS"]["entity_types"]

    pts = extract_points(doc, ["SURVEY_POINTS", "CONTOURS"])
    assert pts.shape[0] > 120  # 121 grid points + contours + extras, deduped
    # Contour vertices carry their constant elevation.
    contour_only = extract_points(doc, ["CONTOURS"])
    assert set(np.round(np.unique(contour_only[:, 2]), 1)) == {210.0, 230.0, 250.0}
    # TEXT spot height parsed.
    all_pts = extract_points(doc, ["SURVEY_POINTS"])
    assert any(np.isclose(all_pts[:, 2], 245.5))
