"""Building footprints (GeoJSON / Overture / OSM export) → 3D obstacles.

Takes a GeoJSON FeatureCollection of building polygons — as exported from
Overture Maps, OSM (Overpass), or any GIS — extrudes each footprint by its
height (``properties.height`` in metres, or ``properties.levels`` × 3 m, or a
default), rasterises the result onto a grid draped over the fused terrain, and
registers it as a **DSM session**: the exact same overlay the drone-LiDAR
pipeline produces, so every existing surface-aware study (profile diffraction
against buildings, obstruction comparison) works unchanged.

Rasterisation uses rasterio.features (no extra deps); the grid lives in
EPSG:4326 with anisotropy handled by separate dx/dy cell sizes so cells are
approximately square metres at the site latitude.
"""
from __future__ import annotations

import math

import numpy as np

DEFAULT_LEVEL_HEIGHT_M = 3.0
MAX_GRID = 1200          # per axis — a footprint import is a local overlay


def _feature_height(props: dict, default_height_m: float) -> float:
    if not isinstance(props, dict):
        return default_height_m
    h = props.get("height")
    if h is not None:
        try:
            return max(float(h), 0.0)
        except (TypeError, ValueError):
            pass
    lv = props.get("levels", props.get("building:levels"))
    if lv is not None:
        try:
            return max(float(lv) * DEFAULT_LEVEL_HEIGHT_M, 0.0)
        except (TypeError, ValueError):
            pass
    return default_height_m


def buildings_to_dsm(geojson: dict, fusion, cell_m: float = 2.0,
                     default_height_m: float = 9.0):
    """FeatureCollection → (DxfTerrainGrid, KnownCrsTransform, stats).

    The grid's values are ``fused terrain + building height`` — a true surface
    model over the footprint bbox, feathered back onto bare terrain outside by
    the existing fusion blending.
    """
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    from ..dxf.georef import KnownCrsTransform
    from ..dxf.gridder import DxfTerrainGrid

    feats = [f for f in geojson.get("features", [])
             if f.get("geometry", {}).get("type") in ("Polygon", "MultiPolygon")]
    if not feats:
        raise ValueError("No building polygons in the GeoJSON")

    # Bounding box over all footprints (+20 m pad).
    lons: list[float] = []
    lats: list[float] = []

    def _walk(coords):
        for c in coords:
            if isinstance(c[0], (int, float)):
                lons.append(float(c[0])); lats.append(float(c[1]))
            else:
                _walk(c)
    for f in feats:
        _walk(f["geometry"]["coordinates"])
    lat_mid = (min(lats) + max(lats)) / 2.0
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = m_per_deg_lat * max(math.cos(math.radians(lat_mid)), 0.05)
    pad_lat = 20.0 / m_per_deg_lat
    pad_lon = 20.0 / m_per_deg_lon
    west, east = min(lons) - pad_lon, max(lons) + pad_lon
    south, north = min(lats) - pad_lat, max(lats) + pad_lat

    dlon = cell_m / m_per_deg_lon
    dlat = cell_m / m_per_deg_lat
    nx = min(int(math.ceil((east - west) / dlon)) + 1, MAX_GRID)
    ny = min(int(math.ceil((north - south) / dlat)) + 1, MAX_GRID)
    dlon = (east - west) / max(nx - 1, 1)
    dlat = (north - south) / max(ny - 1, 1)

    shapes = [(f["geometry"], _feature_height(f.get("properties"), default_height_m))
              for f in feats]
    transform = from_origin(west, north, dlon, dlat)   # row 0 = north
    heights = rasterize(shapes, out_shape=(ny, nx), transform=transform,
                        fill=0.0, dtype="float32", all_touched=True)
    heights = np.flipud(heights)                        # grid row 0 = south

    # Drape over the fused terrain: DSM = ground + building height.
    gx = np.linspace(west, east, nx)
    gy = np.linspace(south, north, ny)
    mlon, mlat = np.meshgrid(gx, gy)
    ground, _w = fusion.fused_elevations(mlat.ravel(), mlon.ravel(), None, None)
    values = ground.reshape(ny, nx) + heights.astype(np.float64)

    grid = DxfTerrainGrid(x0=float(west), y0=float(south),
                          dx=float(dlon), dy=float(dlat), values=values)
    georef = KnownCrsTransform("EPSG:4326")
    stats = {
        "buildings": len(feats),
        "cell_m": cell_m,
        "grid": [nx, ny],
        "max_height_m": round(float(heights.max()), 1),
        "covered_fraction": round(float((heights > 0).mean()), 4),
    }
    return grid, georef, stats
