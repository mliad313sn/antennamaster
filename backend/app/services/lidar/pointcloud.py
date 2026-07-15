"""Drone LiDAR / point-cloud → Digital Surface Model (DSM).

A drone LiDAR survey captures the *real* 3D world — building roofs, tree
canopy, stockpiles, parked haul trucks — at centimetre resolution.  Feeding
that into the RF engine replaces the statistical clutter model (ITU-R P.2108,
which only guesses a land-use loss) with actual physical obstructions the
diffraction math can bend over.

This module parses ``.las`` / ``.laz`` files (laspy + lazrs), rasterises the
points into a **DSM** — the maximum return height per cell, i.e. the top of
whatever the beam hits — and packages it as a regular elevation grid in the
cloud's projected CRS.  That grid reuses the exact ``DxfTerrainGrid`` /
``KnownCrsTransform`` interface the terrain-fusion engine already consumes, so
a profile or coverage run over the DSM footprint computes Deygout diffraction
against the surveyed surface, and the fusion feathers it back onto the SRTM
base outside the flown area.

A ground DSM (min return, or LAS classification 2) gives the bare-earth DTM, so
per-object heights (building = DSM − DTM) are available too.
"""
from __future__ import annotations

import io

import numpy as np

from ..dxf.gridder import DxfTerrainGrid

# Cap the DSM raster so a dense survey cannot allocate an enormous grid.
MAX_GRID_CELLS = 800


def parse_las(data: bytes) -> dict:
    """Parse LAS/LAZ bytes → point arrays, CRS (if embedded) and bounds."""
    import laspy
    las = laspy.read(io.BytesIO(data))
    x = np.asarray(las.x, dtype=np.float64)
    y = np.asarray(las.y, dtype=np.float64)
    z = np.asarray(las.z, dtype=np.float64)
    try:
        classification = np.asarray(las.classification, dtype=np.int16)
    except Exception:
        classification = np.zeros(x.shape, dtype=np.int16)
    epsg = None
    try:
        crs = las.header.parse_crs()
        if crs is not None:
            epsg = crs.to_epsg()
    except Exception:
        epsg = None
    return {
        "x": x, "y": y, "z": z, "classification": classification,
        "n_points": int(x.size), "epsg": epsg,
        "bounds": [float(x.min()), float(y.min()),
                   float(x.max()), float(y.max())] if x.size else [0, 0, 0, 0],
    }


def _binned_max(x, y, z, x0, y0, cell, nx, ny):
    """Maximum z per grid cell (surface); empty cells returned as NaN."""
    ix = np.clip(((x - x0) / cell).astype(int), 0, nx - 1)
    iy = np.clip(((y - y0) / cell).astype(int), 0, ny - 1)
    flat = iy * nx + ix
    grid = np.full(nx * ny, -np.inf)
    np.maximum.at(grid, flat, z)
    grid = grid.reshape(ny, nx)
    grid[np.isinf(grid)] = np.nan
    return grid


def _fill_nans_nearest(grid: np.ndarray) -> np.ndarray:
    """Fill empty cells with the nearest observed value so the surface has no
    holes between LiDAR returns (dense clouds leave only small gaps)."""
    mask = np.isnan(grid)
    if not mask.any():
        return grid
    if mask.all():
        return np.zeros_like(grid)
    from scipy.ndimage import distance_transform_edt
    idx = distance_transform_edt(mask, return_distances=False, return_indices=True)
    return grid[tuple(idx)]


def build_dsm_grid(x, y, z, cell_m: float = 2.0,
                   classification=None, ground_class: int = 2
                   ) -> tuple[DxfTerrainGrid, dict]:
    """Rasterise points into a DSM grid (max return per cell).

    Returns the grid (in the cloud's projected units) plus statistics
    including the DTM-derived object heights when ground points are present.
    """
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    z = np.asarray(z, dtype=np.float64)
    if x.size == 0:
        raise ValueError("empty point cloud")
    x0, y0, x1, y1 = x.min(), y.min(), x.max(), y.max()
    w, h = max(x1 - x0, cell_m), max(y1 - y0, cell_m)
    cell = float(cell_m)
    nx = int(np.ceil(w / cell)) + 1
    ny = int(np.ceil(h / cell)) + 1
    # Enforce the cell cap by coarsening if the survey is huge.
    while nx * ny > MAX_GRID_CELLS * MAX_GRID_CELLS:
        cell *= 1.5
        nx = int(np.ceil(w / cell)) + 1
        ny = int(np.ceil(h / cell)) + 1

    dsm = _fill_nans_nearest(_binned_max(x, y, z, x0, y0, cell, nx, ny))
    grid = DxfTerrainGrid(x0=float(x0), y0=float(y0), dx=cell, dy=cell,
                          values=dsm.astype(np.float64))

    stats = {
        "cell_m": cell, "nx": nx, "ny": ny,
        "surface_min_m": round(float(np.nanmin(dsm)), 2),
        "surface_max_m": round(float(np.nanmax(dsm)), 2),
    }
    # Object heights from a bare-earth model when ground points are labelled.
    if classification is not None:
        classification = np.asarray(classification)
        gmask = classification == ground_class
        if gmask.sum() > 3:
            dtm = _fill_nans_nearest(
                _binned_max(x[gmask], y[gmask], -z[gmask], x0, y0, cell, nx, ny))
            dtm = -dtm  # min of z over ground points
            obj = dsm - dtm
            stats["max_object_height_m"] = round(float(np.nanmax(obj)), 2)
            stats["ground_points"] = int(gmask.sum())
    return grid, stats
