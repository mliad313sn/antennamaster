"""In-memory registry of ingested LiDAR surface models (DSM sessions).

Kept process-local and lightweight: a drone DSM is a working overlay for a
study session, not durable tenant data.  Each entry couples the surface grid
with the georeference that maps it onto the globe, so any profile/coverage run
can fuse it exactly like a DXF terrain patch.
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass

import numpy as np

from ..dxf.georef import BaseGeoref
from ..dxf.gridder import DxfTerrainGrid


@dataclass
class DsmSession:
    dsm_id: str
    grid: DxfTerrainGrid
    georef: BaseGeoref
    stats: dict
    bounds_lonlat: list  # [west, south, east, north]


class _DsmStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, DsmSession] = {}

    def add(self, grid: DxfTerrainGrid, georef: BaseGeoref, stats: dict) -> DsmSession:
        # Footprint in lon/lat from the grid corners.
        xs = np.array([grid.x0, grid.x1, grid.x0, grid.x1])
        ys = np.array([grid.y0, grid.y0, grid.y1, grid.y1])
        lon, lat = georef.to_lonlat(xs, ys)
        bounds = [float(lon.min()), float(lat.min()),
                  float(lon.max()), float(lat.max())]
        sess = DsmSession(uuid.uuid4().hex[:12], grid, georef, stats, bounds)
        with self._lock:
            self._items[sess.dsm_id] = sess
        return sess

    def get(self, dsm_id: str) -> DsmSession | None:
        with self._lock:
            return self._items.get(dsm_id)


STORE = _DsmStore()
