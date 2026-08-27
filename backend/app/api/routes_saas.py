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


@router.get("/bom.csv")
def bom_csv(technology: str = Query("custom"),
            sites: int = Query(1, ge=1, le=500)) -> Response:
    """Hardware bill of materials as CSV - the procurement deliverable
    enterprise rollouts attach to a purchase order (line items scaled to the
    fleet, plus CAPEX/OPEX/TCO summary rows)."""
    est = estimate(technology, sites)
    n = est["sites"]
    lines = [f"# AntennaMaster BOM - {technology} x {n} site(s)",
             "item,qty_per_site,qty_total,unit_usd,line_per_site_usd,line_total_usd"]
    for it in est["bom_per_site"]:
        lines.append(
            f"\"{it['item']}\",{it['qty']},{it['qty'] * n},{it['unit_usd']},"
            f"{it['line_usd']},{round(it['line_usd'] * n, 2)}")
    lines += [
        "",
        f"CAPEX per site,,,,,{est['capex_per_site_usd']}",
        f"CAPEX fleet total,,,,,{est['capex_total_usd']}",
        f"OPEX per site / year,,,,,{est['opex_per_site_year_usd']}",
        f"OPEX fleet / year,,,,,{est['opex_total_year_usd']}",
        f"5-year TCO (fleet),,,,,{est['tco_5y_usd']}",
    ]
    return Response(
        content="\n".join(lines) + "\n", media_type="text/csv",
        headers={"Content-Disposition":
                 f'attachment; filename="bom-{technology}-{n}sites.csv"'})


# ------------------------------------------------------------ PDF reports
class ReportRequest(BaseModel):
    # Reject unknown keys so a client still sending the removed
    # served_area_fraction / max_rx_power_dbm gets a loud 422 instead of
    # silently having them ignored.
    model_config = {"extra": "forbid"}

    title: str = Field("RF Coverage Study", max_length=140)
    # Point-to-point section (optional):
    lat1: float | None = Field(None, ge=-90, le=90)
    lon1: float | None = Field(None, ge=-180, le=180)
    lat2: float | None = Field(None, ge=-90, le=90)
    lon2: float | None = Field(None, ge=-180, le=180)
    tx_height_m: float = 20.0
    rx_height_m: float = 10.0
    technology: str | None = None
    dxf_id: str | None = None
    foliage_depth_m: float = 0.0
    rain_rate_mm_h: float = 0.0
    clutter_pct: float = Field(0.0, ge=0, le=99.9)
    surface: bool = False
    # Coverage section (optional): a previously computed raster.  The figures
    # printed for it are read from the STORED study, never from this request --
    # a signed document whose headline number came from the client is a
    # fabrication vector, so the old served_area_fraction / max_rx_power_dbm
    # fields were removed rather than deprecated (extra fields are rejected).
    coverage_id: str | None = None
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
            rain_rate_mm_h=req.rain_rate_mm_h,
            clutter_pct=req.clutter_pct, surface=req.surface,
            user=user)
        study, rf = data["study"], data["rf"]
        points, distance = data["points"], data["distance_m"]

    coverage_png = None
    coverage_stats = None
    study_ref = None
    if req.coverage_id:
        hit = results_store.load("coverage", req.coverage_id)
        if hit is None:
            raise HTTPException(404, "Coverage result expired or unknown")
        coverage_png = hit[0]
        # The citable reference for the map on this page. A reader disputing
        # the plot a year from now can quote it back and ask for the record,
        # or for a re-run; a picture with no reference is just a picture.
        record = (hit[1] or {}).get("record") or {}
        if record.get("digest"):
            study_ref = {
                "coverage_id": req.coverage_id,
                "digest": record["digest"],
                "app_version": (record.get("provenance") or {}).get("app_version"),
                "model": (record.get("request") or {}).get("model")
                         or (record.get("request") or {}).get("technology"),
            }
        # Read the figures the engine computed and stored alongside the raster.
        # Older results predate the stored stats; print nothing rather than
        # inventing a number.
        stored = (hit[1] or {}).get("stats") or {}
        coverage_stats = {
            "served_area_fraction": stored.get("served_area_fraction"),
            "max_rx_power_dbm": stored.get("max_rx_power_dbm"),
        }

    costs = estimate(req.technology or "custom", req.sites) \
        if req.include_costs else None

    logo = None
    org = ""
    if user:
        org = user.get("org_name") or ""
        if user.get("logo_path") and Path(user["logo_path"]).exists():
            logo = Path(user["logo_path"]).read_bytes()
        # PDF export is audit-logged centrally by AuditMiddleware (user + IP).

    pdf = build_report(title=req.title, org_name=org, logo_png=logo,
                       study=study, profile_points=points, rf=rf,
                       distance_m=distance, coverage_png=coverage_png,
                       coverage_stats=coverage_stats, costs=costs,
                       study_ref=study_ref)
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
    job_id = jobs.create_job("coverage", owner_id=user["id"] if user else None)

    def _progress(fraction: float) -> None:
        jobs.set_progress(job_id, fraction)
        jobs.raise_if_cancelled(job_id)   # cooperative stop, checked in-loop

    def _run() -> dict:
        return run_coverage(req, progress_cb=_progress, user=user)

    try:
        jobs.run_in_thread(job_id, _run)
    except jobs.JobsBusyError as exc:
        raise HTTPException(429, str(exc)) from exc
    # Queueing is audit-logged centrally by AuditMiddleware (user + IP).
    return {"job_id": job_id, "poll": f"/api/saas/jobs/{job_id}"}


@router.get("/jobs/{job_id}")
def job_status(job_id: str,
               user: dict | None = Depends(current_user)) -> dict:
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    # Owner-scoped: a job created by an account is visible only to that
    # account (404, not 403, so ids can't be probed).  Ownerless jobs
    # (anonymous / open-mode) stay public.
    owner = jobs.owner_of(job)
    if owner is not None and (user is None or user["id"] != owner):
        raise HTTPException(404, "Unknown job")
    return {k: v for k, v in job.items() if k != "owner_id"}


@router.delete("/jobs/{job_id}")
def cancel_job(job_id: str,
               user: dict | None = Depends(current_user)) -> dict:
    """Stop a running simulation the user no longer wants.

    A full-resolution sweep is ~26 s; without this, a run started with the
    wrong parameters has to be waited out while holding a worker slot.
    """
    job = jobs.get_job(job_id)
    if job is None:
        raise HTTPException(404, "Unknown job")
    owner = jobs.owner_of(job)
    if owner is not None and (user is None or user["id"] != owner):
        raise HTTPException(404, "Unknown job")   # same non-oracle as the poll
    return {"job_id": job_id, "cancelling": jobs.cancel_job(job_id)}
