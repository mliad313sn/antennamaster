"""Geodesic elevation-profile extraction over the DEM tile store.

Given two WGS84 endpoints, samples are laid out along the true geodesic
(WGS84 ellipsoid, via pyproj.Geod) rather than a straight line in lat/lon
space, so long paths keep correct ground distances.
"""
from __future__ import annotations

import numpy as np
from pyproj import Geod

from .tiles import TerrariumTileStore, get_tile_store

_GEOD = Geod(ellps="WGS84")


def geodesic_points(lat1: float, lon1: float, lat2: float, lon2: float,
                    n_samples: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (lats, lons, distances_m) for `n_samples` points including both
    endpoints, evenly spaced along the geodesic."""
    if n_samples < 2:
        raise ValueError("n_samples must be >= 2")
    _, _, total = _GEOD.inv(lon1, lat1, lon2, lat2)
    # npts excludes the endpoints, so ask for n-2 intermediates.
    inter = _GEOD.npts(lon1, lat1, lon2, lat2, n_samples - 2) if n_samples > 2 else []
    lons = np.array([lon1] + [p[0] for p in inter] + [lon2])
    lats = np.array([lat1] + [p[1] for p in inter] + [lat2])
    dists = np.linspace(0.0, total, n_samples)
    return lats, lons, dists


def srtm_profile(lat1: float, lon1: float, lat2: float, lon2: float,
                 n_samples: int = 256,
                 store: TerrariumTileStore | None = None,
                 ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Elevation profile from the global DEM only.

    Returns (lats, lons, distances_m, elevations_m).
    """
    store = store or get_tile_store()
    lats, lons, dists = geodesic_points(lat1, lon1, lat2, lon2, n_samples)
    elevs = store.elevations(lons, lats)
    return lats, lons, dists, elevs
