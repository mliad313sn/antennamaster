"""Render the georeferenced DXF terrain as a semi-transparent hillshade PNG.

Leaflet's ImageOverlay needs an axis-aligned lat/lon rectangle, while the
DXF grid may be rotated relative to north.  We therefore resample the DXF
grid onto a regular lat/lon raster covering the footprint's bounding box;
pixels that fall outside the DXF extent get alpha 0 (fully transparent), so
the overlay hugs the true (possibly rotated) footprint.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

from .georef import BaseGeoref
from .gridder import DxfTerrainGrid

# Simple hypsometric ramp (low -> high): green, yellow-brown, brown, white.
_RAMP = np.array([
    [46, 122, 66],
    [190, 178, 92],
    [150, 100, 60],
    [245, 245, 245],
], dtype=np.float64)


def _colormap(norm: np.ndarray) -> np.ndarray:
    """Map normalized 0..1 elevations through the hypsometric ramp -> (..,3)."""
    pos = np.clip(norm, 0.0, 1.0) * (len(_RAMP) - 1)
    i0 = np.clip(np.floor(pos).astype(int), 0, len(_RAMP) - 2)
    t = (pos - i0)[..., None]
    return _RAMP[i0] * (1 - t) + _RAMP[i0 + 1] * t


def footprint_lonlat(grid: DxfTerrainGrid, georef: BaseGeoref) -> list[list[float]]:
    """DXF bbox corners as a [lat, lon] ring for the Leaflet footprint polygon."""
    xs = np.array([grid.x0, grid.x1, grid.x1, grid.x0])
    ys = np.array([grid.y0, grid.y0, grid.y1, grid.y1])
    lon, lat = georef.to_lonlat(xs, ys)
    return [[float(la), float(lo)] for la, lo in zip(lat, lon)]


def hillshade_png(grid: DxfTerrainGrid, georef: BaseGeoref,
                  px: int = 512, alpha: float = 0.62,
                  azimuth_deg: float = 315.0, altitude_deg: float = 45.0,
                  ) -> tuple[bytes, list[list[float]]]:
    """Render (png_bytes, [[south, west], [north, east]] bounds).

    The raster is a hypsometric tint multiplied by an analytic hillshade,
    with constant alpha inside the footprint and alpha 0 outside.
    """
    ring = footprint_lonlat(grid, georef)
    lats = [p[0] for p in ring]
    lons = [p[1] for p in ring]
    south, north = min(lats), max(lats)
    west, east = min(lons), max(lons)

    # Lat/lon raster over the axis-aligned footprint bbox.
    aspect = (north - south) / max(east - west, 1e-12)
    w = px if aspect <= 1 else max(int(px / aspect), 32)
    h = max(int(w * aspect), 32)
    lon_g = np.linspace(west, east, w)
    lat_g = np.linspace(north, south, h)  # image row 0 = north
    mlon, mlat = np.meshgrid(lon_g, lat_g)

    gx, gy = georef.from_lonlat(mlon.ravel(), mlat.ravel())
    z = grid.sample(gx, gy).reshape(h, w)
    valid = ~np.isnan(z)

    z_filled = np.where(valid, z, np.nanmean(z[valid]) if valid.any() else 0.0)

    # Analytic hillshade from the elevation gradient (meters per raster px).
    m_per_px_x = (east - west) * 111_320.0 * np.cos(np.radians((north + south) / 2)) / w
    m_per_px_y = (north - south) * 111_320.0 / h
    gy_, gx_ = np.gradient(z_filled, m_per_px_y, m_per_px_x)
    az = np.radians(360.0 - azimuth_deg + 90.0)
    alt = np.radians(altitude_deg)
    slope = np.arctan(np.hypot(gx_, gy_))
    aspect_r = np.arctan2(-gx_, gy_)
    shade = (np.sin(alt) * np.cos(slope)
             + np.cos(alt) * np.sin(slope) * np.cos(az - aspect_r))
    shade = np.clip(shade, 0.15, 1.0)

    zmin = float(np.nanmin(z)) if valid.any() else 0.0
    zmax = float(np.nanmax(z)) if valid.any() else 1.0
    norm = (z_filled - zmin) / max(zmax - zmin, 1e-9)
    rgb = (_colormap(norm) * shade[..., None]).astype(np.uint8)

    rgba = np.dstack([rgb, np.where(valid, int(alpha * 255), 0).astype(np.uint8)])
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG")
    return buf.getvalue(), [[south, west], [north, east]]
