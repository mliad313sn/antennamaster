"""Georeferencing of raw DXF drawing coordinates to WGS84 (EPSG:4326).

Three modes are supported, all exposing the same bidirectional interface
(`to_lonlat` / `from_lonlat`, vectorized over numpy arrays):

A. KnownCrsTransform     - the DXF is drawn in a known projected CRS
                           (UTM, Lambert, ...); pyproj does the work.
B. HelmertTransform      - 2D similarity (scale + rotation + translation)
                           solved by least squares from 2-3 control-point
                           pairs (DXF X/Y  <->  Lat/Lon).  Residuals are
                           reported in meters.
C. OriginBearingTransform- user supplies the Lat/Lon of a known DXF point,
                           the bearing of the DXF +Y axis, and the drawing
                           unit scale (meters per unit; 0.3048 for feet).

Modes B and C work through a local Azimuthal-Equidistant plane centered on
the site, so meters are meaningful and the inverse transform is exact.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from pyproj import CRS, Transformer


def _local_metric_transformer(lat0: float, lon0: float) -> tuple[Transformer, Transformer]:
    """(to_local, to_wgs84) transformers for an AEQD plane centered at lat0/lon0."""
    aeqd = CRS.from_proj4(
        f"+proj=aeqd +lat_0={lat0} +lon_0={lon0} +datum=WGS84 +units=m +no_defs"
    )
    wgs84 = CRS.from_epsg(4326)
    fwd = Transformer.from_crs(wgs84, aeqd, always_xy=True)
    inv = Transformer.from_crs(aeqd, wgs84, always_xy=True)
    return fwd, inv


class BaseGeoref:
    """Common interface: DXF drawing coords <-> WGS84 lon/lat."""

    #: multiply DXF Z values by this to get meters
    z_scale: float = 1.0

    def to_lonlat(self, x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError

    def from_lonlat(self, lon: np.ndarray, lat: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        raise NotImplementedError

    def meters_per_unit(self) -> float:
        """Approximate ground meters per DXF drawing unit (for cell sizing)."""
        raise NotImplementedError

    def describe(self) -> dict:
        raise NotImplementedError


# --------------------------------------------------------------------- mode A
class KnownCrsTransform(BaseGeoref):
    """Mode A: the DXF is in a known projected CRS."""

    def __init__(self, crs: str, z_scale: float = 1.0):
        self.crs_input = crs
        self.crs = CRS.from_user_input(crs)
        if self.crs.is_geographic:
            # Allowed, but meters_per_unit becomes latitude-dependent; we use
            # a nominal value at the CRS's center for grid sizing.
            pass
        wgs84 = CRS.from_epsg(4326)
        self._fwd = Transformer.from_crs(self.crs, wgs84, always_xy=True)
        self._inv = Transformer.from_crs(wgs84, self.crs, always_xy=True)
        self.z_scale = z_scale

    def to_lonlat(self, x, y):
        lon, lat = self._fwd.transform(np.asarray(x), np.asarray(y))
        return np.asarray(lon), np.asarray(lat)

    def from_lonlat(self, lon, lat):
        x, y = self._inv.transform(np.asarray(lon), np.asarray(lat))
        return np.asarray(x), np.asarray(y)

    def meters_per_unit(self) -> float:
        if self.crs.is_geographic:
            return 111_320.0  # nominal meters per degree
        # Projected CRS: read the axis unit conversion factor (1.0 for meters,
        # 0.3048 for foot-based state-plane systems, etc.).
        try:
            return float(self.crs.axis_info[0].unit_conversion_factor)
        except Exception:
            return 1.0

    def describe(self) -> dict:
        return {"mode": "known_crs", "crs": self.crs_input,
                "crs_name": self.crs.name, "z_scale": self.z_scale}


# --------------------------------------------------------------------- mode B
@dataclass
class ControlPoint:
    dxf_x: float
    dxf_y: float
    lat: float
    lon: float


class HelmertTransform(BaseGeoref):
    """Mode B: 2D similarity transform solved from 2-3 control points.

    Model (in the local AEQD metric plane):
        E = a*x - b*y + tE
        N = b*x + a*y + tN
    where scale = hypot(a, b) and rotation = atan2(b, a).
    """

    def __init__(self, control_points: list[ControlPoint], z_scale: float = 1.0):
        if not 2 <= len(control_points) <= 3:
            raise ValueError("Helmert georeferencing needs 2 or 3 control points")
        self.control_points = control_points
        self.z_scale = z_scale

        lat0 = float(np.mean([p.lat for p in control_points]))
        lon0 = float(np.mean([p.lon for p in control_points]))
        self._to_local, self._to_wgs = _local_metric_transformer(lat0, lon0)

        # Target coordinates of the control points in the metric plane.
        E, N = self._to_local.transform(
            np.array([p.lon for p in control_points]),
            np.array([p.lat for p in control_points]),
        )
        x = np.array([p.dxf_x for p in control_points])
        y = np.array([p.dxf_y for p in control_points])

        # Least-squares design matrix for [a, b, tE, tN].
        n = len(control_points)
        A = np.zeros((2 * n, 4))
        rhs = np.zeros(2 * n)
        A[0::2, 0], A[0::2, 1], A[0::2, 2] = x, -y, 1.0
        A[1::2, 0], A[1::2, 1], A[1::2, 3] = y, x, 1.0
        rhs[0::2], rhs[1::2] = E, N
        params, *_ = np.linalg.lstsq(A, rhs, rcond=None)
        self.a, self.b, self.tE, self.tN = (float(v) for v in params)

        self.scale = math.hypot(self.a, self.b)
        self.rotation_deg = math.degrees(math.atan2(self.b, self.a))
        if self.scale < 1e-12:
            raise ValueError("Degenerate control points: solved scale is zero "
                             "(are the DXF points coincident?)")

        # Per-point residuals in meters (how far each control point misses
        # after the best-fit transform) - the frontend shows these.
        fitE = self.a * x - self.b * y + self.tE
        fitN = self.b * x + self.a * y + self.tN
        self.residuals_m = np.hypot(fitE - E, fitN - N).tolist()
        self.rms_residual_m = float(np.sqrt(np.mean(np.square(self.residuals_m))))

    def to_lonlat(self, x, y):
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        E = self.a * x - self.b * y + self.tE
        N = self.b * x + self.a * y + self.tN
        lon, lat = self._to_wgs.transform(E, N)
        return np.asarray(lon), np.asarray(lat)

    def from_lonlat(self, lon, lat):
        E, N = self._to_local.transform(np.asarray(lon), np.asarray(lat))
        E = np.asarray(E) - self.tE
        N = np.asarray(N) - self.tN
        det = self.a * self.a + self.b * self.b
        x = (self.a * E + self.b * N) / det
        y = (-self.b * E + self.a * N) / det
        return x, y

    def meters_per_unit(self) -> float:
        return self.scale

    def describe(self) -> dict:
        return {
            "mode": "control_points",
            "scale_m_per_unit": self.scale,
            "rotation_deg": self.rotation_deg,
            "residuals_m": self.residuals_m,
            "rms_residual_m": self.rms_residual_m,
            "z_scale": self.z_scale,
        }


# --------------------------------------------------------------------- mode C
class OriginBearingTransform(BaseGeoref):
    """Mode C: known origin Lat/Lon + bearing of the DXF +Y axis + unit scale.

    `bearing_deg` is the true azimuth (clockwise from north) that the DXF
    +Y axis points to; 0 means the drawing is already north-up.
    `unit_scale` is ground meters per DXF drawing unit (0.3048 for feet).
    `origin_x/origin_y` are the DXF coordinates that sit at the origin Lat/Lon.
    """

    def __init__(self, origin_lat: float, origin_lon: float, bearing_deg: float = 0.0,
                 unit_scale: float = 1.0, origin_x: float = 0.0, origin_y: float = 0.0,
                 z_scale: float | None = None):
        if unit_scale <= 0:
            raise ValueError("unit_scale must be positive")
        self.origin_lat, self.origin_lon = origin_lat, origin_lon
        self.bearing_deg = bearing_deg
        self.unit_scale = unit_scale
        self.origin_x, self.origin_y = origin_x, origin_y
        # Vertical units almost always match horizontal drawing units.
        self.z_scale = unit_scale if z_scale is None else z_scale
        self._to_local, self._to_wgs = _local_metric_transformer(origin_lat, origin_lon)
        b = math.radians(bearing_deg)
        self._cos, self._sin = math.cos(b), math.sin(b)

    def to_lonlat(self, x, y):
        x = (np.asarray(x, dtype=np.float64) - self.origin_x) * self.unit_scale
        y = (np.asarray(y, dtype=np.float64) - self.origin_y) * self.unit_scale
        # Rotate the DXF frame so +Y points along the given true bearing.
        E = x * self._cos + y * self._sin
        N = y * self._cos - x * self._sin
        lon, lat = self._to_wgs.transform(E, N)
        return np.asarray(lon), np.asarray(lat)

    def from_lonlat(self, lon, lat):
        E, N = self._to_local.transform(np.asarray(lon), np.asarray(lat))
        E, N = np.asarray(E), np.asarray(N)
        x = E * self._cos - N * self._sin
        y = N * self._cos + E * self._sin
        return x / self.unit_scale + self.origin_x, y / self.unit_scale + self.origin_y

    def meters_per_unit(self) -> float:
        return self.unit_scale

    def describe(self) -> dict:
        return {
            "mode": "origin_bearing",
            "origin_lat": self.origin_lat, "origin_lon": self.origin_lon,
            "bearing_deg": self.bearing_deg, "unit_scale": self.unit_scale,
            "origin_x": self.origin_x, "origin_y": self.origin_y,
            "z_scale": self.z_scale,
        }


def build_georef(params: dict) -> BaseGeoref:
    """Factory used by the API layer: dispatch on params['mode']."""
    mode = params.get("mode")
    if mode == "known_crs":
        return KnownCrsTransform(crs=params["crs"], z_scale=float(params.get("z_scale", 1.0)))
    if mode == "control_points":
        cps = [ControlPoint(dxf_x=float(p["dxf_x"]), dxf_y=float(p["dxf_y"]),
                            lat=float(p["lat"]), lon=float(p["lon"]))
               for p in params["control_points"]]
        return HelmertTransform(cps, z_scale=float(params.get("z_scale", 1.0)))
    if mode == "origin_bearing":
        return OriginBearingTransform(
            origin_lat=float(params["origin_lat"]),
            origin_lon=float(params["origin_lon"]),
            bearing_deg=float(params.get("bearing_deg", 0.0)),
            unit_scale=float(params.get("unit_scale", 1.0)),
            origin_x=float(params.get("origin_x", 0.0)),
            origin_y=float(params.get("origin_y", 0.0)),
            z_scale=float(params["z_scale"]) if "z_scale" in params else None,
        )
    raise ValueError(f"Unknown georeferencing mode: {mode!r}")
