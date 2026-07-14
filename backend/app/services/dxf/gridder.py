"""Interpolate the scattered DXF point cloud into a regular grid.

The grid lives in DXF drawing coordinates (so it stays regular regardless of
the georeferencing rotation) and stores Z in *meters* (z_scale already
applied by the caller).

Interpolation follows the spec: `scipy.interpolate.griddata` with `linear`
inside the convex hull of the data, falling back to `nearest` at the edges
(linear leaves NaN outside the hull).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.interpolate import griddata

# Cap on grid dimensions to bound memory (400x400 doubles = ~1.2 MB).
MAX_GRID_DIM = 400
MIN_GRID_DIM = 16


@dataclass
class DxfTerrainGrid:
    """Regular elevation grid in DXF drawing coordinates."""

    x0: float          # west edge (DXF units)
    y0: float          # south edge (DXF units)
    dx: float          # cell size, X (DXF units)
    dy: float          # cell size, Y (DXF units)
    values: np.ndarray  # (ny, nx) elevations in METERS; row 0 = south

    @property
    def nx(self) -> int:
        return self.values.shape[1]

    @property
    def ny(self) -> int:
        return self.values.shape[0]

    @property
    def x1(self) -> float:
        return self.x0 + self.dx * (self.nx - 1)

    @property
    def y1(self) -> float:
        return self.y0 + self.dy * (self.ny - 1)

    def sample(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Bilinear sample at DXF coords; NaN outside the grid extent."""
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        fx = (x - self.x0) / self.dx
        fy = (y - self.y0) / self.dy
        inside = (fx >= 0) & (fx <= self.nx - 1) & (fy >= 0) & (fy <= self.ny - 1)
        fx = np.clip(fx, 0, self.nx - 1)
        fy = np.clip(fy, 0, self.ny - 1)
        ix = np.clip(np.floor(fx).astype(int), 0, self.nx - 2)
        iy = np.clip(np.floor(fy).astype(int), 0, self.ny - 2)
        wx = fx - ix
        wy = fy - iy
        v = (self.values[iy, ix] * (1 - wx) * (1 - wy)
             + self.values[iy, ix + 1] * wx * (1 - wy)
             + self.values[iy + 1, ix] * (1 - wx) * wy
             + self.values[iy + 1, ix + 1] * wx * wy)
        return np.where(inside, v, np.nan)

    def edge_distance_cells(self, x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Distance from (x, y) to the nearest grid boundary, in grid cells.

        Negative outside the grid.  Used for feather blending against SRTM.
        """
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        dxs = np.minimum(x - self.x0, self.x1 - x) / self.dx
        dys = np.minimum(y - self.y0, self.y1 - y) / self.dy
        return np.minimum(dxs, dys)


def build_grid(points: np.ndarray, z_scale: float = 1.0,
               target_cells: int = 200) -> DxfTerrainGrid:
    """Grid the scattered (N, 3) DXF point cloud.

    `target_cells` is the nominal resolution along the longer bbox side;
    the actual size is clamped to [MIN_GRID_DIM, MAX_GRID_DIM] and never
    finer than what ~2x the data density supports.
    """
    if points.shape[0] < 3:
        raise ValueError("Need at least 3 non-collinear terrain points to build a grid "
                         f"(got {points.shape[0]})")
    xy = points[:, :2]
    z = points[:, 2] * z_scale

    x_min, y_min = xy.min(axis=0)
    x_max, y_max = xy.max(axis=0)
    w, h = x_max - x_min, y_max - y_min
    if w <= 0 or h <= 0:
        raise ValueError("Terrain points are collinear (zero-area bounding box); "
                         "cannot interpolate a surface")

    # Do not build a grid dramatically denser than the data itself.
    density_dim = int(np.sqrt(points.shape[0]) * 2)
    long_side = max(min(target_cells, max(density_dim, MIN_GRID_DIM)), MIN_GRID_DIM)
    long_side = min(long_side, MAX_GRID_DIM)
    if w >= h:
        nx = long_side
        ny = max(MIN_GRID_DIM, min(MAX_GRID_DIM, int(round(long_side * h / w))))
    else:
        ny = long_side
        nx = max(MIN_GRID_DIM, min(MAX_GRID_DIM, int(round(long_side * w / h))))

    gx = np.linspace(x_min, x_max, nx)
    gy = np.linspace(y_min, y_max, ny)
    mx, my = np.meshgrid(gx, gy)

    # Linear interpolation inside the convex hull...
    grid = griddata(xy, z, (mx, my), method="linear")
    # ...nearest-neighbour fallback fills the NaN fringe at the edges.
    holes = np.isnan(grid)
    if holes.any():
        grid[holes] = griddata(xy, z, (mx[holes], my[holes]), method="nearest")

    return DxfTerrainGrid(
        x0=float(x_min), y0=float(y_min),
        dx=float(gx[1] - gx[0]), dy=float(gy[1] - gy[0]),
        values=grid.astype(np.float64),
    )
