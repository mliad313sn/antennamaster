"""Terrain fusion: high-resolution DXF patch over the global SRTM base.

Inside the DXF bounding box the DXF grid wins; outside it SRTM wins.  In a
band of ~FUSION_FEATHER_CELLS grid cells along the DXF boundary the two are
cross-faded linearly so the fused surface has no artificial step ("cliff")
that would register as a fake knife-edge diffraction obstacle in the RF
physics.

Also implements the sanity validation: if the mean DXF elevation differs
from the mean SRTM elevation over the *same footprint* by more than
VALIDATION_MEAN_DIFF_M, the georeferencing is almost certainly wrong
(feet-vs-meters mix-up or a bad Helmert fit) and a strict warning is raised
to the API layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..dem.profile import geodesic_points
from ..dem.tiles import TerrariumTileStore, get_tile_store
from ..dxf.georef import BaseGeoref
from ..dxf.gridder import DxfTerrainGrid
from ...config import FUSION_FEATHER_CELLS, VALIDATION_MEAN_DIFF_M


@dataclass
class FusedProfile:
    """One elevation profile with per-sample provenance."""

    lats: np.ndarray
    lons: np.ndarray
    distances_m: np.ndarray
    elevations_m: np.ndarray          # fused surface (no curvature applied)
    dxf_weight: np.ndarray            # 0 = pure SRTM ... 1 = pure DXF
    source: list[str] = field(default_factory=list)  # "srtm" | "dxf" | "blend"


class TerrainFusionService:
    """Combines the SRTM tile store with an optional georeferenced DXF grid."""

    def __init__(self, store: TerrariumTileStore | None = None):
        self.store = store or get_tile_store()

    # ------------------------------------------------------------- sampling
    def fused_elevations(self, lats: np.ndarray, lons: np.ndarray,
                         grid: DxfTerrainGrid | None,
                         georef: BaseGeoref | None,
                         feather_cells: float = FUSION_FEATHER_CELLS,
                         ) -> tuple[np.ndarray, np.ndarray]:
        """Fused elevation + DXF weight for arbitrary lon/lat sample arrays."""
        srtm = self.store.elevations(lons, lats)
        if grid is None or georef is None:
            return srtm, np.zeros_like(srtm)

        # Map the query points into the DXF drawing plane and sample the grid.
        gx, gy = georef.from_lonlat(lons, lats)
        dxf = grid.sample(gx, gy)

        # Feather weight: 0 at (and outside) the DXF boundary, ramping to 1
        # once `feather_cells` cells inside it.
        edge = grid.edge_distance_cells(gx, gy)
        w = np.clip(edge / max(feather_cells, 1e-9), 0.0, 1.0)
        w = np.where(np.isnan(dxf), 0.0, w)

        fused = np.where(w > 0, w * np.nan_to_num(dxf) + (1.0 - w) * srtm, srtm)
        return fused, w

    # -------------------------------------------------------------- profile
    def profile(self, lat1: float, lon1: float, lat2: float, lon2: float,
                n_samples: int = 256,
                grid: DxfTerrainGrid | None = None,
                georef: BaseGeoref | None = None) -> FusedProfile:
        """Geodesic TX->RX profile over the fused terrain model."""
        lats, lons, dists = geodesic_points(lat1, lon1, lat2, lon2, n_samples)
        fused, w = self.fused_elevations(lats, lons, grid, georef)
        source = ["dxf" if wi >= 0.5 else ("blend" if wi > 0 else "srtm") for wi in w]
        return FusedProfile(lats=lats, lons=lons, distances_m=dists,
                            elevations_m=fused, dxf_weight=w, source=source)

    # ----------------------------------------------------------- validation
    def validate_against_srtm(self, grid: DxfTerrainGrid, georef: BaseGeoref,
                              max_samples: int = 32) -> dict:
        """Compare mean DXF vs mean SRTM elevation over the DXF footprint.

        A difference above VALIDATION_MEAN_DIFF_M strongly suggests a unit
        mismatch (feet interpreted as meters => ~3.28x elevation error) or a
        bad Helmert/CRS transform placing the DXF on the wrong terrain.
        """
        nx = min(grid.nx, max_samples)
        ny = min(grid.ny, max_samples)
        sx = np.linspace(grid.x0, grid.x1, nx)
        sy = np.linspace(grid.y0, grid.y1, ny)
        mx, my = np.meshgrid(sx, sy)
        dxf_vals = grid.sample(mx.ravel(), my.ravel())

        lon, lat = georef.to_lonlat(mx.ravel(), my.ravel())
        srtm_vals = self.store.elevations(lon, lat)

        ok = ~np.isnan(dxf_vals)
        dxf_mean = float(np.mean(dxf_vals[ok]))
        srtm_mean = float(np.mean(srtm_vals[ok]))
        diff = dxf_mean - srtm_mean

        warning = None
        if abs(diff) > VALIDATION_MEAN_DIFF_M:
            warning = (
                f"DXF mean elevation ({dxf_mean:.1f} m) differs from SRTM mean "
                f"({srtm_mean:.1f} m) by {abs(diff):.1f} m over the same footprint "
                f"(threshold {VALIDATION_MEAN_DIFF_M:.0f} m). This usually means a "
                "unit mismatch (feet vs meters) or an incorrect georeferencing "
                "transform. Verify the unit scale and control points before "
                "trusting simulation results."
            )
        return {
            "dxf_mean_m": dxf_mean,
            "srtm_mean_m": srtm_mean,
            "mean_diff_m": diff,
            "threshold_m": VALIDATION_MEAN_DIFF_M,
            "warning": warning,
        }
