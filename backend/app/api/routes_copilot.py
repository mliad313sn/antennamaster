"""AI copilot endpoints: engine-driven design diagnosis + tool catalog.

``/api/copilot/analyze`` ties the engines together: for a link it runs the
terrain profile AND the height optimizer, then explains the result and quotes
the exact fix; for coverage it advises on holes and interference.  The advice
is deterministic and works offline; an optional Claude narrator rephrases it
when an API key is configured.  ``/api/copilot/tools`` publishes the callable
tool schemas so an external agent can drive the simulator directly.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..services.copilot.advisor import (advise_coverage, advise_link, narrate,
                                        narrate_llm)
from ..services.copilot.tools import tool_catalog
from ..services.rf.technologies import get_technology
from .routes_auth import current_user
from .routes_terrain import resolve_fusion

router = APIRouter(prefix="/api/copilot", tags=["copilot"])


@router.get("/tools")
def tools() -> dict:
    """Machine-readable catalog of the simulator's study endpoints as tools an
    AI agent can call (MCP / function-calling)."""
    return {"tools": tool_catalog()}


class LinkAnalyzeRequest(BaseModel):
    tx_lat: float = Field(ge=-90, le=90)
    tx_lon: float = Field(ge=-180, le=180)
    rx_lat: float = Field(ge=-90, le=90)
    rx_lon: float = Field(ge=-180, le=180)
    technology: str = "custom"
    surface: bool = False
    narrate_with_llm: bool = False


class CoverageAnalyzeRequest(BaseModel):
    # The frontend already holds a coverage result; pass its stats back for
    # advice (no need to re-run the raster).
    stats: dict
    technology: str | None = None
    sinr: dict | None = None
    narrate_with_llm: bool = False


@router.post("/analyze/link")
def analyze_link(req: LinkAnalyzeRequest,
                 user: dict | None = Depends(current_user)) -> dict:
    """Run the profile + height optimizer for a link and return a ranked,
    actionable diagnosis with a quantified fix."""
    try:
        tech = get_technology(req.technology)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    fusion = resolve_fusion(req.surface)
    try:
        prof = fusion.profile(req.tx_lat, req.tx_lon, req.rx_lat, req.rx_lon,
                              n_samples=256)
    except Exception as exc:
        raise HTTPException(502, f"Elevation data unavailable: {exc}") from exc

    import numpy as np

    from ..services.rf.models import deygout_loss_db, path_loss_db
    from ..services.rf.physics import analyze_path, apply_earth_curvature
    from ..services.rf.planning import min_height_m
    from ..services.rf.technologies import effective_sensitivity_dbm

    d, e = prof.distances_m, prof.elevations_m
    freq = float(tech["freq_mhz"])
    h_bs, h_ut = float(tech["h_bs_m"]), float(tech["h_ut_m"])
    rf = analyze_path(d, e, h_bs, h_ut, freq)
    pl, _w = path_loss_db(tech["model"], np.maximum(d[-1:], 1.0), freq,
                          h_bs, h_ut, tech.get("environment", "urban"))
    diff = deygout_loss_db(d, apply_earth_curvature(d, e), h_bs, h_ut, freq)
    rx_power = (tech["tx_power_dbm"] + tech["tx_gain_dbi"] + tech["rx_gain_dbi"]
                + tech.get("mimo_gain_db", 0.0) - tech["losses_db"]
                - float(pl[-1]) - diff)
    margin = rx_power - effective_sensitivity_dbm(tech)
    analysis = {
        "distance_m": round(float(d[-1]), 1), "freq_mhz": freq,
        "los_clear": rf["line_of_sight_clear"],
        "fresnel_clearance_ratio": round(rf["fresnel_clearance_ratio"], 3),
        "diffraction_loss_db": round(float(diff), 1),
        "rx_power_dbm": round(float(rx_power), 1),
        "margin_db": round(float(margin), 1),
    }
    heights = {"criteria": {c: {
        "min_tx_height_m": min_height_m(d, e, freq, h_ut, "tx", c),
    } for c in ("los", "f1_60")}}

    findings = advise_link(analysis, heights)
    summary = (narrate_llm(findings, "radio link",
                           context=f"{req.technology} over "
                                   f"{analysis['distance_m'] / 1000:.1f} km")
               if req.narrate_with_llm else narrate(findings, "radio link"))
    return {"analysis": analysis, "findings": findings, "summary": summary}


@router.post("/analyze/coverage")
def analyze_coverage(req: CoverageAnalyzeRequest,
                     user: dict | None = Depends(current_user)) -> dict:
    """Diagnose an area-coverage result (holes, interference, band choice)."""
    tech = None
    if req.technology:
        try:
            tech = get_technology(req.technology)
        except ValueError:
            tech = None
    findings = advise_coverage(req.stats, tech, req.sinr)
    summary = (narrate_llm(findings, "coverage study")
               if req.narrate_with_llm else narrate(findings, "coverage study"))
    return {"findings": findings, "summary": summary}
