"""Drone LiDAR / point-cloud endpoints.

Upload a ``.las``/``.laz`` survey → a Digital Surface Model that overrides the
statistical clutter with real 3D obstructions, then run a profile whose
diffraction is computed against the surveyed buildings/trees/machinery.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from ..services.rf.models import deygout_loss_db
from ..services.rf.physics import analyze_path, apply_earth_curvature
from ..services.rf.technologies import get_technology
from .routes_auth import current_user
from .routes_terrain import resolve_fusion

router = APIRouter(prefix="/api/lidar", tags=["lidar"])

MAX_LAS_MB = 60


@router.post("/upload")
async def upload_pointcloud(
    file: UploadFile = File(...),
    epsg: int | None = Form(None),
    cell_m: float = Form(2.0),
    user: dict | None = Depends(current_user),
) -> dict:
    """Ingest a LiDAR point cloud and build a Digital Surface Model overlay.

    The CRS is read from the file when embedded; otherwise pass ``epsg`` (or,
    for already-geographic clouds, EPSG:4326 is assumed from the coordinate
    range).
    """
    raw = await file.read()
    if len(raw) > MAX_LAS_MB * 1024 * 1024:
        raise HTTPException(413, f"Point cloud exceeds {MAX_LAS_MB} MB")
    from ..services.lidar.pointcloud import build_dsm_grid, parse_las
    try:
        pc = parse_las(raw)
    except Exception as exc:
        raise HTTPException(422, f"Could not parse point cloud: {exc}") from exc
    if pc["n_points"] == 0:
        raise HTTPException(422, "Point cloud contains no points")

    code = epsg or pc["epsg"]
    if code is None:
        bx = pc["bounds"]
        if abs(bx[0]) <= 180 and abs(bx[1]) <= 90 and abs(bx[2]) <= 180:
            code = 4326                       # coordinates look geographic
        else:
            raise HTTPException(
                422, "No CRS embedded in the file; supply epsg= for the survey")
    from ..services.dxf.georef import KnownCrsTransform
    try:
        georef = KnownCrsTransform(f"EPSG:{code}")
    except Exception as exc:
        raise HTTPException(422, f"Unknown EPSG {code}: {exc}") from exc

    try:
        grid, stats = build_dsm_grid(
            pc["x"], pc["y"], pc["z"], cell_m=max(cell_m, 0.25),
            classification=pc["classification"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc

    from ..services.lidar.store import STORE
    sess = STORE.add(grid, georef, stats)
    return {
        "dsm_id": sess.dsm_id, "n_points": pc["n_points"], "epsg": int(code),
        "stats": stats, "bounds": sess.bounds_lonlat,
    }


@router.get("/{dsm_id}/info")
def dsm_info(dsm_id: str) -> dict:
    from ..services.lidar.store import STORE
    sess = STORE.get(dsm_id)
    if sess is None:
        raise HTTPException(404, "Unknown DSM id")
    return {"dsm_id": dsm_id, "stats": sess.stats, "bounds": sess.bounds_lonlat}


@router.get("/{dsm_id}/profile")
def dsm_profile(
    dsm_id: str,
    lat1: float = Query(ge=-90, le=90), lon1: float = Query(ge=-180, le=180),
    lat2: float = Query(ge=-90, le=90), lon2: float = Query(ge=-180, le=180),
    h_tx_m: float = Query(5.0, ge=0, le=200),
    h_rx_m: float = Query(1.5, ge=0, le=200),
    freq_mhz: float | None = Query(None, gt=0),
    technology: str | None = Query(None),
    samples: int = Query(256, ge=16, le=2048),
    k_factor: float = Query(4.0 / 3.0, gt=0.1, le=10),
) -> dict:
    """Profile whose diffraction is computed against the surveyed 3D surface,
    with a bare-terrain comparison so the building/canopy effect is explicit."""
    from ..services.lidar.store import STORE
    sess = STORE.get(dsm_id)
    if sess is None:
        raise HTTPException(404, "Unknown DSM id")
    eff_freq = freq_mhz
    if technology is not None:
        try:
            eff_freq = freq_mhz or get_technology(technology)["freq_mhz"]
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    eff_freq = eff_freq or 2400.0

    fusion = resolve_fusion(False)

    def run(grid, georef):
        prof = fusion.profile(lat1, lon1, lat2, lon2, n_samples=samples,
                              grid=grid, georef=georef)
        d, e = prof.distances_m, prof.elevations_m
        rf = analyze_path(d, e, h_tx_m, h_rx_m, eff_freq, k=k_factor)
        diff = float(deygout_loss_db(d, apply_earth_curvature(d, e, k=k_factor),
                                     h_tx_m, h_rx_m, eff_freq))
        return prof, rf, diff

    try:
        surf_prof, surf_rf, surf_diff = run(sess.grid, sess.georef)
        bare_prof, bare_rf, bare_diff = run(None, None)
    except Exception as exc:
        raise HTTPException(502, f"Profile failed: {exc}") from exc

    points = [{"d": round(float(di), 1),
               "surface_elev": round(float(se), 2),
               "bare_elev": round(float(be), 2),
               "obstruction_m": round(float(se - be), 2)}
              for di, se, be in zip(surf_prof.distances_m,
                                    surf_prof.elevations_m,
                                    bare_prof.elevations_m)]
    return {
        "dsm_id": dsm_id, "freq_mhz": eff_freq,
        "surface": {"los_clear": surf_rf["line_of_sight_clear"],
                    "fresnel_clearance_ratio": round(surf_rf["fresnel_clearance_ratio"], 3),
                    "diffraction_loss_db": round(surf_diff, 1)},
        "bare_terrain": {"los_clear": bare_rf["line_of_sight_clear"],
                         "diffraction_loss_db": round(bare_diff, 1)},
        "extra_loss_from_surface_db": round(surf_diff - bare_diff, 1),
        "max_obstruction_m": round(max((p["obstruction_m"] for p in points),
                                       default=0.0), 2),
        "points": points,
    }
