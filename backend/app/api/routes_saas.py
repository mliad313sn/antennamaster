"""SaaS value endpoints: CAPEX/OPEX estimates, PDF reports, async jobs."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..services import results_store
from ..services.saas import db, jobs
from ..services.saas.costs import estimate
from ..services.saas.report import build_report
from ..services.saas.tiers import require_feature
from .routes_auth import current_user
from ..services.saas.tiers import check_preset_allowed
from .routes_rf import CoverageRequest, run_coverage
from .routes_terrain import terrain_profile

router = APIRouter(prefix="/api/saas", tags=["saas"])


# ------------------------------------------------------------- CAPEX/OPEX
@router.get("/costs")
def cost_estimate(technology: str = Query("custom"),
                  sites: int = Query(1, ge=1, le=500)) -> dict:
    """Per-site BOM + fleet CAPEX/OPEX + 5-year TCO for the Command Center
    and ROI pitches."""
    return estimate(technology, sites)


# ------------------------------------------------------------ PDF reports
class ReportRequest(BaseModel):
    title: str = Field("RF Coverage Study", max_length=140)
    # Point-to-point section (optional):
    lat1: float | None = None
    lon1: float | None = None
    lat2: float | None = None
    lon2: float | None = None
    tx_height_m: float = 20.0
    rx_height_m: float = 10.0
    technology: str | None = None
    dxf_id: str | None = None
    foliage_depth_m: float = 0.0
    rain_rate_mm_h: float = 0.0
    # Coverage section (optional): a previously computed raster.
    coverage_id: str | None = None
    served_area_fraction: float | None = None
    max_rx_power_dbm: float | None = None
    # Equipment section (optional):
    include_costs: bool = True
    sites: int = Field(1, ge=1, le=500)


@router.post("/report.pdf")
def report_pdf(req: ReportRequest,
               user: dict | None = Depends(current_user)) -> Response:
    """Branded executive PDF: link budget matrix, terrain profile chart,
    coverage heatmap, equipment list. White-label logo for Enterprise."""
    require_feature(user, "pdf_export")

    study = rf = None
    points = None
    distance = None
    if None not in (req.lat1, req.lon1, req.lat2, req.lon2):
        data = terrain_profile(
            lat1=req.lat1, lon1=req.lon1, lat2=req.lat2, lon2=req.lon2,
            samples=256, dxf_id=req.dxf_id,
            tx_height_m=req.tx_height_m, rx_height_m=req.rx_height_m,
            freq_mhz=None, k_factor=4.0 / 3.0,
            technology=req.technology, model=None, environment=None,
            tx_power_dbm=None, tx_gain_dbi=None, rx_gain_dbi=None,
            losses_db=None, rx_sensitivity_dbm=None,
            foliage_depth_m=req.foliage_depth_m,
            rain_rate_mm_h=req.rain_rate_mm_h)
        study, rf = data["study"], data["rf"]
        points, distance = data["points"], data["distance_m"]

    coverage_png = None
    coverage_stats = None
    if req.coverage_id:
        hit = results_store.load("coverage", req.coverage_id)
        if hit is None:
            raise HTTPException(404, "Coverage result expired or unknown")
        coverage_png = hit[0]
        coverage_stats = {"served_area_fraction": req.served_area_fraction,
                          "max_rx_power_dbm": req.max_rx_power_dbm or 0.0}

    costs = estimate(req.technology or "custom", req.sites) \
        if req.include_costs else None

    logo = None
    org = ""
    if user:
        org = user.get("org_name") or ""
        if user.get("logo_path") and Path(user["logo_path"]).exists():
            logo = Path(user["logo_path"]).read_bytes()
        db.log_action(user["id"], "pdf_export", req.title)

    pdf = build_report(title=req.title, org_name=org, logo_png=logo,
                       study=study, profile_points=points, rf=rf,
                       distance_m=distance, coverage_png=coverage_png,
                       coverage_stats=coverage_stats, costs=costs)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition":
                             'attachment; filename="rf-study.pdf"'})


# -------------------------------------------------------------- async jobs
@router.post("/coverage/async")
def coverage_async(req: CoverageRequest,
                   user: dict | None = Depends(current_user)) -> dict:
    """Queue a coverage simulation as a background job with live progress -
    keeps the UI responsive for heavy (high-res / long-radius) runs."""
    check_preset_allowed(user, req.technology)   # entitlements before queueing
    job_id = jobs.create_job("coverage")

    def _run() -> dict:
        return run_coverage(req, progress_cb=lambda f: jobs.set_progress(job_id, f))

    jobs.run_in_thread(job_id, _run)
    if user:
        db.log_action(user["id"], "coverage_async",
                      f"{req.technology} r={req.radius_km}km")
    return {"job_id": job_id, "poll": f"/api/saas/jobs/{job_id}"}


@router.get("/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    return job
