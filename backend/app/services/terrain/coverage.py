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
    def compute_polar(self, lat: float, lon: float, tech: dict,
                      radius_m: float = 10_000.0,
                      n_radials: int = 180, n_steps: int = 100,
                      antenna_azimuth_deg: float | None = None,
                      antenna_beamwidth_deg: float = 65.0,
                      downtilt_deg: float = 0.0,
                      vertical_beamwidth_deg: float = 10.0,
                      antenna_pattern: dict | None = None,
                      shadow_margin_db: float = 0.0,
                      foliage_depth_m: float = 0.0,
                      rain_rate_mm_h: float = 0.0,
                      grid: DxfTerrainGrid | None = None,
                      georef: BaseGeoref | None = None,
                      k: float = K_FACTOR_DEFAULT) -> dict:
        """Run the physics and return the polar field (no rasterization).

        Returns {az, dist, rx_power, margin, tx_elev, warnings}."""
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

        # Elevation angle of every sample as seen from the TX antenna
        # (negative = below the horizon) - used by both pattern paths.
        dh = (elev + h_ut) - (tx_elev + h_bs)                   # (R, S) meters
        elev_angle = np.degrees(np.arctan2(dh, dist_g))         # (R, S)

        if antenna_pattern is not None:
            # Measured MSI pattern: sum-of-cuts H(az offset) + V(elev offset)
            # about a boresight tilted down by mechanical + electrical tilt.
            from ..rf.antenna import pattern_attenuation
            boresight = -(downtilt_deg
                          + float(antenna_pattern.get("electrical_tilt_deg", 0.0)))
            az_off = (az - (antenna_azimuth_deg or 0.0))[:, None]  # (R, 1)
            elev_off = boresight - elev_angle                      # (R, S)
            ant_gain = -pattern_attenuation(antenna_pattern,
                                            np.broadcast_to(az_off, elev_off.shape),
                                            elev_off)
        else:
            # Parametric 3GPP model: horizontal parabolic sector (25 dB
            # front-to-back) + vertical parabola with downtilt (20 dB floor).
            ant_gain = np.zeros((n_radials, 1))
            if antenna_azimuth_deg is not None:
                delta = (az - antenna_azimuth_deg + 180.0) % 360.0 - 180.0
                ant_gain = -np.minimum(
                    12.0 * (delta / antenna_beamwidth_deg) ** 2, 25.0)[:, None]
            if downtilt_deg != 0.0 or antenna_azimuth_deg is not None:
                v_delta = elev_angle - (-downtilt_deg)
                ant_gain = ant_gain - np.minimum(
                    12.0 * (v_delta / max(vertical_beamwidth_deg, 1.0)) ** 2, 20.0)

        # Environmental excess losses: last-mile foliage clutter at every RX
        # location, rain over the effective path, atmospheric gases (only
        # material above ~10 GHz but always physically present).
        from ..rf.environment import (foliage_loss_db, gaseous_attenuation_db_per_km,
                                      rain_specific_attenuation)
        env_loss = np.zeros(n_steps)
        if foliage_depth_m > 0:
            env_loss += foliage_loss_db(freq, foliage_depth_m)
        env_loss += gaseous_attenuation_db_per_km(freq) * dist / 1000.0
        if rain_rate_mm_h > 0:
            gamma_r = rain_specific_attenuation(freq, rain_rate_mm_h)
            d0 = 35.0 * np.exp(-0.015 * min(rain_rate_mm_h, 100.0))
            d_km = dist / 1000.0
            env_loss += gamma_r * d_km / (1.0 + d_km / d0)

        mimo = float(tech.get("mimo_gain_db", 0.0))
        rx_power = (tech["tx_power_dbm"] + tech["tx_gain_dbi"] + tech["rx_gain_dbi"]
                    + mimo - tech["losses_db"] + ant_gain - pl - diff_loss
                    - env_loss[None, :])
        # Shadow-fade (location variability) margin: subtract before the
        # served test so "served" means the target location probability,
        # not the 50% median a bare link budget gives.  Sensitivity derives
        # from channel bandwidth + NF + SINR when the preset defines them.
        from ..rf.technologies import effective_sensitivity_dbm
        margin = rx_power - effective_sensitivity_dbm(tech) - shadow_margin_db

        return {"az": az, "dist": dist, "dist_g": dist_g,
                "rx_power": rx_power, "margin": margin,
                "tx_elev": tx_elev, "warnings": warnings}

    def simulate(self, lat: float, lon: float, tech: dict,
                 radius_m: float = 10_000.0,
                 n_radials: int = 180, n_steps: int = 100,
                 antenna_azimuth_deg: float | None = None,
                 antenna_beamwidth_deg: float = 65.0,
                 downtilt_deg: float = 0.0,
                 vertical_beamwidth_deg: float = 10.0,
                 antenna_pattern: dict | None = None,
                 shadow_margin_db: float = 0.0,
                 foliage_depth_m: float = 0.0,
                 rain_rate_mm_h: float = 0.0,
                 grid: DxfTerrainGrid | None = None,
                 georef: BaseGeoref | None = None,
                 k: float = K_FACTOR_DEFAULT,
                 raster_px: int = 512) -> CoverageResult:
        polar = self.compute_polar(
            lat, lon, tech, radius_m=radius_m,
            n_radials=n_radials, n_steps=n_steps,
            antenna_azimuth_deg=antenna_azimuth_deg,
            antenna_beamwidth_deg=antenna_beamwidth_deg,
            downtilt_deg=downtilt_deg,
            vertical_beamwidth_deg=vertical_beamwidth_deg,
            antenna_pattern=antenna_pattern,
            shadow_margin_db=shadow_margin_db,
            foliage_depth_m=foliage_depth_m,
            rain_rate_mm_h=rain_rate_mm_h,
            grid=grid, georef=georef, k=k)

        png, bounds = self._rasterize(lat, lon, polar["az"], polar["dist"],
                                      polar["margin"], radius_m, raster_px)

        # Area-weight the served statistic: a polar cell's ground area grows
        # linearly with distance, so an unweighted mean over-counts the
        # (nearly always served) samples close to the mast.
        w_area = polar["dist_g"] / polar["dist_g"].sum()
        served_frac = float(np.sum((polar["margin"] >= 0.0) * w_area))
        return CoverageResult(
            coverage_id=uuid.uuid4().hex[:12],
            png=png, bounds=bounds,
            legend=[{"margin_db": m, "color": "#%02x%02x%02x" % c, "label": l}
                    for m, c, l in LEGEND_STEPS],
            stats={
                "served_area_fraction": round(served_frac, 4),
                "radius_m": radius_m,
                "n_radials": n_radials, "n_steps": n_steps,
                "tx_elevation_m": polar["tx_elev"],
                "max_rx_power_dbm": round(float(polar["rx_power"].max()), 1),
            },
            warnings=polar["warnings"],
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


# Best-server site colors: the categorical palette order (CVD-safe).
SITE_COLORS = [
    (42, 120, 214), (27, 175, 122), (237, 161, 0), (0, 131, 0),
    (74, 58, 167), (227, 73, 72), (232, 123, 164), (235, 104, 52),
]


def composite_best_server(sites: list[dict], raster_px: int = 768,
                          ) -> tuple[bytes, list[list[float]], list[dict]]:
    """Composite several sites' polar fields into one best-server raster.

    ``sites``: [{lat, lon, radius_m, name, polar}] where ``polar`` is the
    dict from CoverageEngine.compute_polar.  Every raster pixel is painted
    in the color of the site delivering the strongest RX power there,
    provided that site's fade-margin test passes (else transparent).

    Returns (png, [[south, west], [north, east]], per_site_stats).
    """
    # Union bounding box of all coverage discs.
    boxes = []
    for s in sites:
        lat_r = np.degrees(s["radius_m"] / EARTH_RADIUS_M)
        lon_r = lat_r / max(np.cos(np.radians(s["lat"])), 0.05)
        boxes.append((s["lat"] - lat_r, s["lon"] - lon_r,
                      s["lat"] + lat_r, s["lon"] + lon_r))
    south = min(b[0] for b in boxes)
    west = min(b[1] for b in boxes)
    north = max(b[2] for b in boxes)
    east = max(b[3] for b in boxes)

    aspect = (north - south) / max(east - west, 1e-9)
    if aspect <= 1:
        w, h = raster_px, max(int(raster_px * aspect), 32)
    else:
        h, w = raster_px, max(int(raster_px / aspect), 32)
    lat_g = np.linspace(north, south, h)
    lon_g = np.linspace(west, east, w)
    mlon, mlat = np.meshgrid(lon_g, lat_g)

    best_rx = np.full((h, w), -np.inf)
    best_margin = np.full((h, w), -np.inf)
    best_idx = np.full((h, w), -1, dtype=int)

    for i, s in enumerate(sites):
        polar = s["polar"]
        az, dist = polar["az"], polar["dist"]
        m_e = (mlon - s["lon"]) * np.cos(np.radians(s["lat"])) \
            * (np.pi / 180.0) * EARTH_RADIUS_M
        m_n = (mlat - s["lat"]) * (np.pi / 180.0) * EARTH_RADIUS_M
        pix_d = np.hypot(m_e, m_n)
        pix_az = (np.degrees(np.arctan2(m_e, m_n)) + 360.0) % 360.0
        ai = np.round(pix_az / (360.0 / len(az))).astype(int) % len(az)
        d_step = dist[1] - dist[0] if len(dist) > 1 else dist[0]
        di = np.clip(np.round((pix_d - dist[0]) / d_step).astype(int),
                     0, len(dist) - 1)
        inside = pix_d <= s["radius_m"]
        rx = np.where(inside, polar["rx_power"][ai, di], -np.inf)
        better = rx > best_rx
        best_rx = np.where(better, rx, best_rx)
        best_margin = np.where(better, polar["margin"][ai, di], best_margin)
        best_idx = np.where(better, i, best_idx)

    served = np.isfinite(best_rx) & (best_margin >= 0.0)
    rgba = np.zeros((h, w, 4), dtype=np.uint8)
    stats: list[dict] = []
    total_served = max(int(served.sum()), 1)
    for i, s in enumerate(sites):
        mask = served & (best_idx == i)
        color = SITE_COLORS[i % len(SITE_COLORS)]
        rgba[mask, 0], rgba[mask, 1], rgba[mask, 2] = color
        rgba[mask, 3] = 150
        stats.append({
            "name": s.get("name") or f"Site {i + 1}",
            "color": "#%02x%02x%02x" % color,
            "best_server_share": round(float(mask.sum()) / total_served, 4),
            "max_rx_power_dbm": round(float(s["polar"]["rx_power"].max()), 1),
        })

    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG")
    return buf.getvalue(), [[south, west], [north, east]], stats
