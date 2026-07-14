"""RF study endpoints: technology presets, propagation models, area coverage."""
from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..services import results_store
from ..services.dxf.store import get_dxf_store
from ..services.rf import antenna as antenna_store
from ..services.rf.models import MODEL_INFO
from ..services.rf.technologies import TECHNOLOGIES, get_technology
from ..services.terrain.coverage import CoverageEngine, composite_best_server
from .routes_terrain import get_fusion_service

router = APIRouter(prefix="/api/rf", tags=["rf"])


class CoverageRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    technology: str = "custom"
    radius_km: float = Field(10.0, gt=0.1, le=150.0)
    dxf_id: str | None = None
    # Optional overrides of the technology preset:
    freq_mhz: float | None = Field(None, gt=0)
    model: str | None = None
    environment: str | None = None
    tx_power_dbm: float | None = None
    tx_gain_dbi: float | None = None
    rx_gain_dbi: float | None = None
    losses_db: float | None = None
    rx_sensitivity_dbm: float | None = None
    h_bs_m: float | None = Field(None, gt=0)
    h_ut_m: float | None = Field(None, gt=0)
    # Sector antenna (omni when azimuth is null):
    antenna_azimuth_deg: float | None = Field(None, ge=0, lt=360)
    antenna_beamwidth_deg: float = Field(65.0, gt=5, le=360)
    # Measured pattern (MSI Planet upload) replacing the parametric model:
    antenna_id: str | None = None
    downtilt_deg: float = Field(0.0, ge=-10, le=20)
    vertical_beamwidth_deg: float = Field(10.0, gt=1, le=90)
    # Location-variability (shadow fade) margin subtracted before the
    # served test - design to ~90/95% area instead of the 50% median.
    shadow_margin_db: float = Field(0.0, ge=0, le=30)
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    # Environmental excess losses (last-mile clutter / weather):
    foliage_depth_m: float = Field(0.0, ge=0, le=400)
    rain_rate_mm_h: float = Field(0.0, ge=0, le=150)
    # Simulation resolution:
    n_radials: int = Field(180, ge=36, le=720)
    n_steps: int = Field(100, ge=20, le=400)
    raster_px: int = Field(512, ge=128, le=1024)


@router.get("/technologies")
def list_technologies() -> dict:
    """All radio-study presets (2G/3G/4G/5G, PMR, broadcast, WLAN, IoT, PtP)."""
    return {"technologies": [{"key": k, **v} for k, v in TECHNOLOGIES.items()]}


@router.get("/models")
def list_models() -> dict:
    """All propagation models with validity ranges."""
    return {"models": [{"key": k, **v} for k, v in MODEL_INFO.items()]}


def _resolve_tech(req: CoverageRequest) -> dict:
    try:
        tech = get_technology(req.technology)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for f in ("freq_mhz", "model", "environment", "tx_power_dbm", "tx_gain_dbi",
              "rx_gain_dbi", "losses_db", "rx_sensitivity_dbm", "h_bs_m", "h_ut_m"):
        v = getattr(req, f)
        if v is not None:
            tech[f] = v
    if tech["model"] not in MODEL_INFO:
        raise HTTPException(422, f"Unknown propagation model: {tech['model']!r}")
    return tech


@router.post("/coverage")
def simulate_coverage(req: CoverageRequest) -> dict:
    """Run an area coverage simulation from a TX site over the fused terrain."""
    tech = _resolve_tech(req)

    grid = georef = None
    if req.dxf_id:
        session = get_dxf_store().get(req.dxf_id)
        if session is None:
            raise HTTPException(404, f"Unknown DXF id: {req.dxf_id}")
        if not session.ensure_ready():
            raise HTTPException(409, "DXF has not been georeferenced yet")
        grid, georef = session.grid, session.georef

    pattern = None
    if req.antenna_id:
        pattern = antenna_store.load_antenna(req.antenna_id)
        if pattern is None:
            raise HTTPException(404, f"Unknown antenna id: {req.antenna_id}")
        # A measured pattern carries its own gain; use it unless overridden.
        if req.tx_gain_dbi is None:
            tech["tx_gain_dbi"] = float(pattern.get("gain_dbi", tech["tx_gain_dbi"]))

    engine = CoverageEngine(get_fusion_service())
    try:
        result = engine.simulate(
            req.lat, req.lon, tech, radius_m=req.radius_km * 1000.0,
            n_radials=req.n_radials, n_steps=req.n_steps,
            antenna_azimuth_deg=req.antenna_azimuth_deg,
            antenna_beamwidth_deg=req.antenna_beamwidth_deg,
            downtilt_deg=req.downtilt_deg,
            vertical_beamwidth_deg=req.vertical_beamwidth_deg,
            antenna_pattern=pattern,
            shadow_margin_db=req.shadow_margin_db,
            foliage_depth_m=req.foliage_depth_m,
            rain_rate_mm_h=req.rain_rate_mm_h,
            k=req.k_factor,
            grid=grid, georef=georef,
            raster_px=req.raster_px,
        )
    except Exception as exc:  # DEM fetch failure -> 502, not a stacktrace
        raise HTTPException(502, f"Coverage simulation failed: {exc}") from exc

    # Disk-backed so any worker can serve the PNG and restarts lose nothing.
    results_store.save("coverage", result.coverage_id, result.png,
                       {"bounds": result.bounds})

    return {
        "coverage_id": result.coverage_id,
        "png_url": f"/api/rf/coverage/{result.coverage_id}.png",
        "bounds": result.bounds,
        "legend": result.legend,
        "stats": result.stats,
        "technology": {**tech, "key": req.technology},
        "warnings": result.warnings,
    }


@router.get("/coverage/{coverage_id}.png")
def coverage_png(coverage_id: str) -> Response:
    hit = results_store.load("coverage", coverage_id)
    if hit is None:
        raise HTTPException(404, "Coverage result expired or unknown")
    return Response(content=hit[0], media_type="image/png",
                    headers={"Cache-Control": "max-age=3600"})


@router.get("/coverage/{coverage_id}.kmz")
def coverage_kmz(coverage_id: str) -> Response:
    """Coverage raster as a KMZ GroundOverlay - opens in Google Earth / GIS,
    the deliverable format planners hand to clients."""
    hit = results_store.load("coverage", coverage_id)
    if hit is None:
        raise HTTPException(404, "Coverage result expired or unknown")
    png, meta = hit
    (south, west), (north, east) = meta.get("bounds", [[0, 0], [0, 0]])
    kml = f"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <GroundOverlay>
    <name>AntennaMaster coverage {coverage_id}</name>
    <Icon><href>coverage.png</href></Icon>
    <LatLonBox>
      <north>{north}</north><south>{south}</south>
      <east>{east}</east><west>{west}</west>
    </LatLonBox>
  </GroundOverlay>
</kml>"""
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml)
        z.writestr("coverage.png", png)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.google-earth.kmz",
        headers={"Content-Disposition":
                 f'attachment; filename="coverage-{coverage_id}.kmz"'})


# ----------------------------------------------------------- antennas (MSI)
@router.post("/antenna")
async def upload_antenna(file: UploadFile = File(...)) -> dict:
    """Upload an MSI Planet (.msi/.pln/.ant) measured antenna pattern."""
    raw = await file.read()
    if len(raw) > 2 * 1024 * 1024:
        raise HTTPException(413, "Pattern file exceeds 2 MB")
    try:
        text = raw.decode("utf-8", errors="replace")
        return antenna_store.save_antenna(text)
    except ValueError as exc:
        raise HTTPException(422, f"Could not parse antenna pattern: {exc}") from exc


@router.get("/antennas")
def list_antennas() -> dict:
    """All uploaded antenna patterns (name, gain, -3 dB beamwidths)."""
    return {"antennas": antenna_store.list_antennas()}


# --------------------------------------------------------- multi-site study
class SiteIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    name: str | None = None
    antenna_azimuth_deg: float | None = Field(None, ge=0, lt=360)
    downtilt_deg: float = Field(0.0, ge=-10, le=20)


class MultiCoverageRequest(BaseModel):
    sites: list[SiteIn] = Field(min_length=1, max_length=8)
    technology: str = "custom"
    radius_km: float = Field(10.0, gt=0.1, le=150.0)
    dxf_id: str | None = None
    antenna_id: str | None = None
    antenna_beamwidth_deg: float = Field(65.0, gt=5, le=360)
    shadow_margin_db: float = Field(0.0, ge=0, le=30)
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    n_radials: int = Field(120, ge=36, le=360)
    n_steps: int = Field(80, ge=20, le=200)
    # Link budget overrides shared by every site:
    freq_mhz: float | None = Field(None, gt=0)
    model: str | None = None
    environment: str | None = None
    tx_power_dbm: float | None = None
    tx_gain_dbi: float | None = None
    rx_gain_dbi: float | None = None
    losses_db: float | None = None
    rx_sensitivity_dbm: float | None = None
    h_bs_m: float | None = Field(None, gt=0)
    h_ut_m: float | None = Field(None, gt=0)


@router.post("/coverage/multi")
def simulate_multi_coverage(req: MultiCoverageRequest) -> dict:
    """Best-server composite over up to 8 sites: each raster pixel takes the
    color of the site delivering the strongest served signal there - the
    cluster view planners use to check hand-over zones and holes."""
    try:
        tech = get_technology(req.technology)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    for f in ("freq_mhz", "model", "environment", "tx_power_dbm", "tx_gain_dbi",
              "rx_gain_dbi", "losses_db", "rx_sensitivity_dbm", "h_bs_m", "h_ut_m"):
        v = getattr(req, f)
        if v is not None:
            tech[f] = v
    if tech["model"] not in MODEL_INFO:
        raise HTTPException(422, f"Unknown propagation model: {tech['model']!r}")

    pattern = None
    if req.antenna_id:
        pattern = antenna_store.load_antenna(req.antenna_id)
        if pattern is None:
            raise HTTPException(404, f"Unknown antenna id: {req.antenna_id}")
        if req.tx_gain_dbi is None:
            tech["tx_gain_dbi"] = float(pattern.get("gain_dbi", tech["tx_gain_dbi"]))

    grid = georef = None
    if req.dxf_id:
        session = get_dxf_store().get(req.dxf_id)
        if session is None:
            raise HTTPException(404, f"Unknown DXF id: {req.dxf_id}")
        if not session.ensure_ready():
            raise HTTPException(409, "DXF has not been georeferenced yet")
        grid, georef = session.grid, session.georef

    engine = CoverageEngine(get_fusion_service())
    radius_m = req.radius_km * 1000.0
    computed = []
    warnings: list[str] = []
    try:
        for s in req.sites:
            polar = engine.compute_polar(
                s.lat, s.lon, dict(tech), radius_m=radius_m,
                n_radials=req.n_radials, n_steps=req.n_steps,
                antenna_azimuth_deg=s.antenna_azimuth_deg,
                antenna_beamwidth_deg=req.antenna_beamwidth_deg,
                downtilt_deg=s.downtilt_deg,
                antenna_pattern=pattern,
                shadow_margin_db=req.shadow_margin_db,
                k=req.k_factor, grid=grid, georef=georef)
            warnings.extend(w for w in polar["warnings"] if w not in warnings)
            computed.append({"lat": s.lat, "lon": s.lon, "name": s.name,
                             "radius_m": radius_m, "polar": polar})
    except Exception as exc:
        raise HTTPException(502, f"Coverage simulation failed: {exc}") from exc

    png, bounds, site_stats = composite_best_server(computed)
    import uuid as _uuid
    result_id = _uuid.uuid4().hex[:12]
    results_store.save("coverage", result_id, png, {"bounds": bounds})

    return {
        "coverage_id": result_id,
        "png_url": f"/api/rf/coverage/{result_id}.png",
        "bounds": bounds,
        "legend": [{"label": s["name"], "color": s["color"],
                    "margin_db": 0} for s in site_stats],
        "stats": {
            "sites": site_stats,
            "served_area_fraction": None,
            "radius_m": radius_m,
            "tx_elevation_m": computed[0]["polar"]["tx_elev"],
            "max_rx_power_dbm": max(s["max_rx_power_dbm"] for s in site_stats),
        },
        "technology": {**tech, "key": req.technology},
        "warnings": warnings,
    }
