"""Elevation-profile and link-analysis endpoints over the fused terrain."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

import numpy as np

from ..services.dxf.store import get_dxf_store
from ..services.rf.models import MODEL_INFO, deygout_loss_db, path_loss_db
from ..services.rf.physics import analyze_path, apply_earth_curvature
from ..services.rf.technologies import get_technology, link_budget
from ..services.terrain.fusion import TerrainFusionService

# Process-wide fusion service (shares the DEM tile cache across requests).
_fusion = TerrainFusionService()


def get_fusion_service() -> TerrainFusionService:
    return _fusion

router = APIRouter(prefix="/api/terrain", tags=["terrain"])


@router.get("/elevation")
def point_elevation(lat: float = Query(ge=-90, le=90),
                    lon: float = Query(ge=-180, le=180),
                    dxf_id: str | None = None) -> dict:
    """Fused elevation at a single point (SRTM, or DXF where available)."""
    fusion = get_fusion_service()
    grid = georef = None
    if dxf_id:
        session = get_dxf_store().get(dxf_id)
        if session and session.grid is not None:
            grid, georef = session.grid, session.georef
    elev, w = fusion.fused_elevations(np.array([lat]), np.array([lon]), grid, georef)
    return {"lat": lat, "lon": lon, "elevation_m": float(elev[0]),
            "source": "dxf" if w[0] >= 0.5 else ("blend" if w[0] > 0 else "srtm")}


@router.get("/profile")
def terrain_profile(
    lat1: float = Query(ge=-90, le=90), lon1: float = Query(ge=-180, le=180),
    lat2: float = Query(ge=-90, le=90), lon2: float = Query(ge=-180, le=180),
    samples: int = Query(256, ge=16, le=2048),
    dxf_id: str | None = None,
    tx_height_m: float = Query(20.0, ge=0),
    rx_height_m: float = Query(10.0, ge=0),
    # No default: with a technology preset the preset frequency wins unless
    # explicitly overridden; without one we fall back to 446 MHz (PMR).
    freq_mhz: float | None = Query(None, gt=0),
    k_factor: float = Query(4.0 / 3.0, gt=0.1, le=10),
    # Optional full radio study along the path (any preset: 2G..5G, PMR, ...).
    technology: str | None = Query(None),
    model: str | None = Query(None),
    environment: str | None = Query(None),
    tx_power_dbm: float | None = Query(None),
    tx_gain_dbi: float | None = Query(None),
    rx_gain_dbi: float | None = Query(None),
    losses_db: float | None = Query(None),
    rx_sensitivity_dbm: float | None = Query(None),
) -> dict:
    """TX->RX elevation profile over the fused terrain, plus RF link analysis.

    Per-sample `source` tells the frontend which segments came from SRTM vs
    the DXF patch (for provenance color-coding).  `terrain_curved_m` has the
    k-factor earth bulge applied and is what the LOS/Fresnel numbers use.
    """
    fusion = get_fusion_service()

    grid = georef = None
    dxf_active = False
    if dxf_id:
        session = get_dxf_store().get(dxf_id)
        if session is None:
            raise HTTPException(404, f"Unknown DXF id: {dxf_id}")
        if session.grid is None:
            raise HTTPException(409, "DXF has not been georeferenced yet")
        grid, georef = session.grid, session.georef
        dxf_active = True

    try:
        prof = fusion.profile(lat1, lon1, lat2, lon2, n_samples=samples,
                              grid=grid, georef=georef)
    except Exception as exc:  # DEM fetch failures surface as 502, not 500
        raise HTTPException(502, f"Elevation data unavailable: {exc}") from exc

    # Effective frequency: explicit param > technology preset > 446 MHz.
    tech_preview = None
    if technology is not None:
        try:
            tech_preview = get_technology(technology)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
    eff_freq = freq_mhz if freq_mhz is not None else (
        tech_preview["freq_mhz"] if tech_preview else 446.0)

    rf = analyze_path(prof.distances_m, prof.elevations_m,
                      tx_height_m=tx_height_m, rx_height_m=rx_height_m,
                      freq_mhz=eff_freq, k=k_factor)

    # Optional technology study: model path loss + Deygout diffraction on the
    # curved profile -> per-sample RX power + link budget at the RX end.
    study = None
    rx_power_per_point: np.ndarray | None = None
    if technology is not None:
        tech = tech_preview  # already resolved above
        overrides = {"model": model, "environment": environment,
                     "tx_power_dbm": tx_power_dbm, "tx_gain_dbi": tx_gain_dbi,
                     "rx_gain_dbi": rx_gain_dbi, "losses_db": losses_db,
                     "rx_sensitivity_dbm": rx_sensitivity_dbm,
                     "freq_mhz": freq_mhz, "h_bs_m": tx_height_m or None,
                     "h_ut_m": rx_height_m or None}
        for key, val in overrides.items():
            if val is not None:
                tech[key] = val
        if tech["model"] not in MODEL_INFO:
            raise HTTPException(422, f"Unknown propagation model: {tech['model']!r}")

        d = prof.distances_m
        curved = apply_earth_curvature(d, prof.elevations_m, k=k_factor)
        pl, warnings = path_loss_db(tech["model"], np.maximum(d, 1.0),
                                    tech["freq_mhz"], tech["h_bs_m"],
                                    tech["h_ut_m"], tech["environment"])
        # Deygout diffraction on each TX->sample sub-path (interior samples).
        diff = np.zeros_like(d)
        for i in range(2, len(d)):
            diff[i] = deygout_loss_db(d[: i + 1], curved[: i + 1],
                                      tech["h_bs_m"], tech["h_ut_m"],
                                      tech["freq_mhz"])
        rx_power_per_point = (tech["tx_power_dbm"] + tech["tx_gain_dbi"]
                              + tech["rx_gain_dbi"] - tech["losses_db"]
                              - pl - diff)
        budget = link_budget(tech, float(pl[-1]), float(diff[-1]))
        study = {
            "technology": {**tech, "key": technology},
            "path_loss_db": round(float(pl[-1]), 1),
            "diffraction_loss_db": round(float(diff[-1]), 1),
            "rx_power_dbm": round(budget["rx_power_dbm"], 1),
            "margin_db": round(budget["margin_db"], 1),
            "served": budget["served"],
            "warnings": warnings,
        }

    return {
        "samples": samples,
        "dxf_id": dxf_id if dxf_active else None,
        "distance_m": prof.distances_m[-1] - prof.distances_m[0],
        "points": [
            {
                "d": round(float(d), 1),
                "lat": float(la), "lon": float(lo),
                "elev": round(float(e), 2),
                "elev_curved": round(float(ec), 2),
                "los": round(float(l), 2),
                "fresnel_lower": round(float(fl), 2),
                "source": s,
                "dxf_weight": round(float(w), 3),
                **({"rx_power_dbm": round(float(rx_power_per_point[i]), 1)}
                   if rx_power_per_point is not None else {}),
            }
            for i, (d, la, lo, e, ec, l, fl, s, w) in enumerate(zip(
                prof.distances_m, prof.lats, prof.lons, prof.elevations_m,
                rf["terrain_curved_m"], rf["los_m"], rf["fresnel1_lower_m"],
                prof.source, prof.dxf_weight))
        ],
        "study": study,
        "rf": {
            "line_of_sight_clear": rf["line_of_sight_clear"],
            "fresnel_clearance_ratio": round(rf["fresnel_clearance_ratio"], 3),
            "knife_edge_loss_db": round(rf["knife_edge_loss_db"], 2),
            "worst_obstruction_index": rf["worst_obstruction_index"],
            "worst_obstruction_v": round(rf["worst_obstruction_v"], 3),
            "k_factor": rf["k_factor"],
            "freq_mhz": eff_freq,
            "tx_height_m": tx_height_m,
            "rx_height_m": rx_height_m,
        },
    }
