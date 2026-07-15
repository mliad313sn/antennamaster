"""Heightmap tiles for the CesiumJS 3D terrain provider.

CesiumJS renders a 3D globe from a terrain provider that serves per-tile
elevation grids.  Rather than depend on Cesium Ion (a paid, online service),
we feed Cesium's ``CustomHeightmapTerrainProvider`` directly from our own fused
SRTM+DXF model: for each requested (level, x, y) tile we compute its geographic
rectangle in Cesium's default ``GeographicTilingScheme`` and sample the fused
terrain on a small regular grid, returned as a compact int16 array.  The result
is a true 3D digital-twin terrain built entirely from the data the platform
already has — offline-capable and consistent with the 2D physics.
"""
from __future__ import annotations

import numpy as np

# Cesium GeographicTilingScheme defaults: 2 root tiles in X, 1 in Y, covering
# the full -180..180 / -90..90 geographic extent.
ROOT_TILES_X = 2
ROOT_TILES_Y = 1


def tile_rectangle(level: int, x: int, y: int) -> tuple[float, float, float, float]:
    """Geographic bounds (west, south, east, north) in degrees of a Cesium
    GeographicTilingScheme tile."""
    tiles_x = ROOT_TILES_X * (2 ** level)
    tiles_y = ROOT_TILES_Y * (2 ** level)
    lon_w = 360.0 / tiles_x
    lat_h = 180.0 / tiles_y
    west = -180.0 + x * lon_w
    east = west + lon_w
    north = 90.0 - y * lat_h
    south = north - lat_h
    return west, south, east, north


# Below this Cesium level a single tile spans a huge area; sampling real
# elevation there would fetch hundreds of DEM tiles for no visible relief.
# We return a flat sea-level tile and let real relief refine as the user zooms
# toward the area of interest (standard terrain level-of-detail behaviour).
MIN_DETAIL_LEVEL = 8


def heightmap_int16(fusion, level: int, x: int, y: int, size: int = 65,
                    grid=None, georef=None,
                    min_detail_level: int = MIN_DETAIL_LEVEL) -> bytes:
    """int16 (metres, row-major north->south, west->east) heightmap for a tile.

    ``size`` is the grid edge (Cesium wants a fixed width==height, default 65).
    Sampling reuses the fused-terrain service, so the 3D relief matches the 2D
    physics; an optional DXF grid/georef refines the patch it covers.  Levels
    below ``min_detail_level`` return a flat tile to avoid fetching the whole
    hemisphere's DEM for a coarse view.
    """
    if level < min_detail_level:
        return np.zeros((size, size), dtype=np.int16).tobytes()
    west, south, east, north = tile_rectangle(level, x, y)
    lons = np.linspace(west, east, size)
    # Row 0 = north; Cesium heightmap rows run north -> south.
    lats = np.linspace(north, south, size)
    mlon, mlat = np.meshgrid(lons, lats)
    fused, _w = fusion.fused_elevations(mlat.ravel(), mlon.ravel(), grid, georef)
    heights = np.round(fused.reshape(size, size)).astype(np.int16)
    return heights.tobytes()
