"""Two-way talk-back endpoints: bidirectional LMR link & area studies.

The downlink-only propagation of a classic predictor cannot answer the
question every land-mobile-radio tender asks: does the *portable* talk back?
These endpoints compute talk-out AND talk-in, grade both in DAQ (delivered
audio quality) and report the limiting direction and reliable talk-back area.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..services.rf.models import MODEL_INFO
from ..services.rf.twoway import (PENETRATION_CLASSES, repeater_cascade,
                                  twoway_coverage, twoway_evaluate_receiver)
from ..services.saas import jobs
from ..services.terrain.coverage import CoverageEngine
from .routes_auth import current_user
from .routes_terrain import resolve_fusion

router = APIRouter(prefix="/api/rf/twoway", tags=["rf", "two-way"])


class BaseStation(BaseModel):
    freq_mhz: float = Field(gt=0)
    model: str = "okumura_hata"
    environment: str = "suburban"
    h_bs_m: float = Field(30.0, gt=0, le=500)
    tx_power_dbm: float = Field(44.0, ge=-30, le=90)
    ant_gain_dbi: float = Field(6.0, ge=-10, le=60)   # used both ways
    rx_sensitivity_dbm: float = Field(-119.0, le=0)   # the base receiver
    losses_db: float = Field(3.0, ge=0, le=30)


class Portable(BaseModel):
    tx_power_dbm: float = Field(37.0, ge=-30, le=60)  # 37 dBm = 5 W
    ant_gain_dbi: float = Field(0.0, ge=-10, le=20)
    rx_sensitivity_dbm: float = Field(-119.0, le=0)
    h_ut_m: float = Field(1.5, gt=0, le=50)
    body_loss_db: float = Field(4.0, ge=0, le=20)
    penetration_class: str = "on_street"
    penetration_db: float | None = Field(None, ge=0, le=60)


class LinkRequest(BaseModel):
    base: BaseStation
    portable: Portable
    tx_lat: float = Field(ge=-90, le=90)
    tx_lon: float = Field(ge=-180, le=180)
    rx_lat: float = Field(ge=-90, le=90)
    rx_lon: float = Field(ge=-180, le=180)
    target_daq: float = Field(3.4, ge=1.0, le=4.5)
    faded_margin_db: float = Field(20.0, ge=0, le=40)
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    foliage_depth_m: float = Field(0.0, ge=0, le=400)
    rain_rate_mm_h: float = Field(0.0, ge=0, le=150)
    clutter_pct: float = Field(0.0, ge=0, le=99.9)
    surface: bool = False


class CoverageRequest(BaseModel):
    base: BaseStation
    portable: Portable
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_km: float = Field(8.0, gt=0.1, le=60.0)
    target_daq: float = Field(3.4, ge=1.0, le=4.5)
    faded_margin_db: float = Field(20.0, ge=0, le=40)
    antenna_azimuth_deg: float | None = Field(None, ge=0, lt=360)
    antenna_beamwidth_deg: float = Field(65.0, gt=5, le=360)
    downtilt_deg: float = Field(0.0, ge=-10, le=20)
    shadow_margin_db: float = Field(0.0, ge=0, le=30)
    clutter_pct: float = Field(0.0, ge=0, le=99.9)
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    surface: bool = False
    n_radials: int = Field(120, ge=36, le=360)
    n_steps: int = Field(80, ge=20, le=200)


class CascadeRequest(BaseModel):
    corridor_km: float = Field(gt=0, le=2000)
    reliable_range_km: float = Field(gt=0, le=100)
    overlap_pct: float = Field(15.0, ge=0, le=90)


def _check_model(model: str) -> None:
    if model not in MODEL_INFO:
        raise HTTPException(422, f"Unknown propagation model: {model!r}")


@router.get("/penetration-classes")
def penetration_classes() -> dict:
    """Portable penetration classes (on-street / in-vehicle / in-building)."""
    return {"classes": [{"key": k, **v} for k, v in PENETRATION_CLASSES.items()],
            "default_body_loss_db": 4.0}


@router.post("/link")
def twoway_link(req: LinkRequest,
                user: dict | None = Depends(current_user)) -> dict:
    """Bidirectional talk-back verdict for one base<->portable link: talk-out,
    talk-in, DAQ each way, the limiting direction and a reliability verdict."""
    _check_model(req.base.model)
    fusion = resolve_fusion(req.surface)
    try:
        return twoway_evaluate_receiver(
            fusion, req.base.model_dump(), req.portable.model_dump(),
            req.tx_lat, req.tx_lon, req.rx_lat, req.rx_lon,
            target_daq=req.target_daq, faded_margin_db=req.faded_margin_db,
            k=req.k_factor, foliage_depth_m=req.foliage_depth_m,
            rain_rate_mm_h=req.rain_rate_mm_h, clutter_pct=req.clutter_pct)
    except Exception as exc:
        raise HTTPException(502, f"Two-way link analysis failed: {exc}") from exc


@router.post("/coverage")
def twoway_area(req: CoverageRequest,
                user: dict | None = Depends(current_user)) -> dict:
    """Area talk-back study: talk-out, talk-in and reliable (both-direction)
    served fractions with the limiting-direction breakdown."""
    _check_model(req.base.model)
    engine = CoverageEngine(resolve_fusion(req.surface))
    try:
        with jobs.sim_slot():
            return twoway_coverage(
                engine, req.base.model_dump(), req.portable.model_dump(),
                req.lat, req.lon, radius_m=req.radius_km * 1000.0,
                target_daq=req.target_daq, faded_margin_db=req.faded_margin_db,
                antenna_azimuth_deg=req.antenna_azimuth_deg,
                antenna_beamwidth_deg=req.antenna_beamwidth_deg,
                downtilt_deg=req.downtilt_deg,
                shadow_margin_db=req.shadow_margin_db,
                clutter_pct=req.clutter_pct, k=req.k_factor,
                n_radials=req.n_radials, n_steps=req.n_steps)
    except jobs.SimBusyError as exc:
        raise HTTPException(429, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"Two-way coverage failed: {exc}") from exc


@router.post("/repeater-cascade")
def repeater_chain(req: CascadeRequest) -> dict:
    """Repeaters needed for continuous talk-back along a corridor (spacing,
    count, positions) given a per-repeater reliable range and hand-off overlap."""
    try:
        return repeater_cascade(req.corridor_km, req.reliable_range_km,
                                req.overlap_pct)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
