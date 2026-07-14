"""Area coverage simulation: radial sweep over the fused terrain model.

For one transmitter site the engine shoots ``n_radials`` geodesic rays out to
``radius_m``, samples the fused (SRTM + optional DXF) terrain along each ray,
applies the k=4/3 earth bulge, computes the strongest-knife-edge diffraction
loss cumulatively along every ray, adds the technology's empirical path loss
model, an optional sector antenna pattern, and rasterizes received power to a
web-map RGBA overlay (transparent where unserved / beyond the radius).

This is the same architecture Radio Mobile / SPLAT! use (polar sweep +
raster), chosen because it reuses one terrain profile per azimuth instead of
computing an independent profile per pixel.
"""
from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field

import numpy as np
from PIL import Image
from pyproj import Geod

from ..dxf.georef import BaseGeoref
from ..dxf.gridder import DxfTerrainGrid
from ..rf.models import ke_loss_array, path_loss_db
from ..rf.physics import EARTH_RADIUS_M, K_FACTOR_DEFAULT
from .fusion import TerrainFusionService

_GEOD = Geod(ellps="WGS84")
C_LIGHT = 299_792_458.0

# Signal-strength ramp: single blue hue, dark = strong (sequential encoding).
# Thresholds are offsets above the technology's receiver sensitivity.
LEGEND_STEPS = [
    # (margin_db >=, color, label)
    (30.0, (13, 54, 107), "Excellent (≥ 30 dB margin)"),
    (20.0, (24, 79, 149), "Very good (≥ 20 dB)"),
    (12.0, (37, 106, 191), "Good (≥ 12 dB)"),
    (6.0, (85, 152, 231), "Fair (≥ 6 dB)"),
    (0.0, (158, 197, 244), "Marginal (≥ 0 dB)"),
]


@dataclass
class CoverageResult:
    coverage_id: str
    png: bytes
    bounds: list[list[float]]        # [[south, west], [north, east]]
    legend: list[dict]
    stats: dict
    warnings: list[str] = field(default_factory=list)


class CoverageEngine:
    def __init__(self, fusion: TerrainFusionService):
        self.fusion = fusion

    # ------------------------------------------------------------ simulate
    def simulate(self, lat: float, lon: float, tech: dict,
                 radius_m: float = 10_000.0,
                 n_radials: int = 180, n_steps: int = 100,
                 antenna_azimuth_deg: float | None = None,
                 antenna_beamwidth_deg: float = 65.0,
                 downtilt_deg: float = 0.0,
                 vertical_beamwidth_deg: float = 10.0,
                 shadow_margin_db: float = 0.0,
                 grid: DxfTerrainGrid | None = None,
                 georef: BaseGeoref | None = None,
                 k: float = K_FACTOR_DEFAULT,
                 raster_px: int = 512) -> CoverageResult:
        freq = float(tech["freq_mhz"])
        h_bs, h_ut = float(tech["h_bs_m"]), float(tech["h_ut_m"])

        # ---- 1) polar fan of geodesic sample points -----------------------
        az = np.linspace(0.0, 360.0, n_radials, endpoint=False)
        dist = np.linspace(radius_m / n_steps, radius_m, n_steps)
        az_g, dist_g = np.meshgrid(az, dist, indexing="ij")     # (R, S)
        flat_az, flat_d = az_g.ravel(), dist_g.ravel()
        lons, lats, _ = _GEOD.fwd(np.full(flat_az.shape, lon),
                                  np.full(flat_az.shape, lat),
                                  flat_az, flat_d)

        # ---- 2) fused terrain along every ray -----------------------------
        elev_flat, _w = self.fusion.fused_elevations(
            np.asarray(lats), np.asarray(lons), grid, georef)
        elev = elev_flat.reshape(n_radials, n_steps)
        tx_elev = float(self.fusion.fused_elevations(
            np.array([lat]), np.array([lon]), grid, georef)[0][0])

        # ---- 3) per-ray diffraction: strongest knife edge up to each step -
        # v_ij for candidate edge j on the sub-path TX -> step i, evaluated on
        # the k-curved profile.  Vectorized per ray as (S, S) broadcasts.
        lam = C_LIGHT / (freq * 1e6)
        d = dist                                                # (S,)
        d_i = d[:, None]                                        # target step i
        d_j = d[None, :]                                        # edge candidate j
        seg_valid = d_j < d_i                                    # only edges before i
        d2 = np.where(seg_valid, d_i - d_j, 1.0)
        bulge = d_j * d2 / (2.0 * k * EARTH_RADIUS_M)
        sqrt_term = np.sqrt(2.0 * d_i / (lam * np.maximum(d_j, 1.0) * d2))

        e_tx = tx_elev + h_bs
        diff_loss = np.zeros((n_radials, n_steps))
        for r in range(n_radials):
            e_rx = elev[r] + h_ut                               # (S,) endpoint at i
            los = e_tx + (e_rx[:, None] - e_tx) * (d_j / d_i)   # (S, S)
            h_obs = elev[r][None, :] + bulge - los
            v = np.where(seg_valid, h_obs * sqrt_term, -np.inf)
            diff_loss[r] = ke_loss_array(v.max(axis=1))         # worst edge per step

        # ---- 4) empirical path loss + link budget -------------------------
        pl, warnings = path_loss_db(tech["model"], dist_g.ravel(), freq,
                                    h_bs, h_ut, tech.get("environment", "urban"))
        pl = pl.reshape(n_radials, n_steps)

        # Horizontal sector pattern (3GPP parabolic, 25 dB front-to-back).
        ant_gain = np.zeros((n_radials, 1))
        if antenna_azimuth_deg is not None:
            delta = (az - antenna_azimuth_deg + 180.0) % 360.0 - 180.0
            ant_gain = -np.minimum(
                12.0 * (delta / antenna_beamwidth_deg) ** 2, 25.0)[:, None]

        # Vertical pattern with mechanical/electrical downtilt: elevation
        # angle of each sample as seen from the TX antenna (negative = below
        # horizon), 3GPP parabolic in the vertical plane, 20 dB floor.
        if downtilt_deg != 0.0 or antenna_azimuth_deg is not None:
            dh = (elev + h_ut) - (tx_elev + h_bs)               # (R, S) meters
            elev_angle = np.degrees(np.arctan2(dh, dist_g))     # (R, S)
            v_delta = elev_angle - (-downtilt_deg)              # boresight below horizon
            ant_gain = ant_gain - np.minimum(
                12.0 * (v_delta / max(vertical_beamwidth_deg, 1.0)) ** 2, 20.0)

        rx_power = (tech["tx_power_dbm"] + tech["tx_gain_dbi"] + tech["rx_gain_dbi"]
                    - tech["losses_db"] + ant_gain - pl - diff_loss)
        # Shadow-fade (location variability) margin: subtract before the
        # served test so "served" means the target location probability,
        # not the 50% median a bare link budget gives.
        margin = rx_power - tech["rx_sensitivity_dbm"] - shadow_margin_db

        # ---- 5) rasterize the polar field to a lat/lon RGBA overlay -------
        png, bounds = self._rasterize(lat, lon, az, dist, margin, radius_m, raster_px)

        # Area-weight the served statistic: a polar cell's ground area grows
        # linearly with distance, so an unweighted mean over-counts the
        # (nearly always served) samples close to the mast.
        w_area = dist_g / dist_g.sum()
        served_frac = float(np.sum((margin >= 0.0) * w_area))
        return CoverageResult(
            coverage_id=uuid.uuid4().hex[:12],
            png=png, bounds=bounds,
            legend=[{"margin_db": m, "color": "#%02x%02x%02x" % c, "label": l}
                    for m, c, l in LEGEND_STEPS],
            stats={
                "served_area_fraction": round(served_frac, 4),
                "radius_m": radius_m,
                "n_radials": n_radials, "n_steps": n_steps,
                "tx_elevation_m": tx_elev,
                "max_rx_power_dbm": round(float(rx_power.max()), 1),
            },
            warnings=warnings,
        )

    # ------------------------------------------------------------ raster
    @staticmethod
    def _rasterize(lat: float, lon: float, az: np.ndarray, dist: np.ndarray,
                   margin: np.ndarray, radius_m: float, px: int,
                   ) -> tuple[bytes, list[list[float]]]:
        """Nearest-neighbour polar -> equirectangular raster around the TX."""
        # Bounding box of the coverage disc.
        lat_r = np.degrees(radius_m / EARTH_RADIUS_M)
        lon_r = lat_r / max(np.cos(np.radians(lat)), 0.05)
        south, north = lat - lat_r, lat + lat_r
        west, east = lon - lon_r, lon + lon_r

        lat_g = np.linspace(north, south, px)                  # row 0 = north
        lon_g = np.linspace(west, east, px)
        mlon, mlat = np.meshgrid(lon_g, lat_g)

        # Equirectangular local approximation is fine at coverage-map scale
        # (< a few hundred km): meters east/north from the TX per pixel.
        m_e = (mlon - lon) * np.cos(np.radians(lat)) * (np.pi / 180.0) * EARTH_RADIUS_M
        m_n = (mlat - lat) * (np.pi / 180.0) * EARTH_RADIUS_M
        pix_d = np.hypot(m_e, m_n)
        pix_az = (np.degrees(np.arctan2(m_e, m_n)) + 360.0) % 360.0

        # Index into the polar grid.
        az_step = 360.0 / len(az)
        ai = np.round(pix_az / az_step).astype(int) % len(az)
        d_step = dist[1] - dist[0] if len(dist) > 1 else dist[0]
        di = np.clip(np.round((pix_d - dist[0]) / d_step).astype(int), 0, len(dist) - 1)
        m = margin[ai, di]

        inside = pix_d <= radius_m
        rgba = np.zeros((px, px, 4), dtype=np.uint8)
        for thresh, color, _label in LEGEND_STEPS:              # strongest first
            mask = inside & (m >= thresh) & (rgba[:, :, 3] == 0)
            rgba[mask, 0], rgba[mask, 1], rgba[mask, 2] = color
            rgba[mask, 3] = 150                                  # ~0.59 alpha
        buf = io.BytesIO()
        Image.fromarray(rgba, "RGBA").save(buf, format="PNG")
        return buf.getvalue(), [[south, west], [north, east]]
