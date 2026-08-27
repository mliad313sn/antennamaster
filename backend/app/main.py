"""FastAPI application entry point.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging

import math

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

# Server-side logs for operators: broad route-level excepts log the full
# traceback here before returning a sanitized HTTP error to the client.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

from .api.routes_auth import router as auth_router
from .api.routes_basemap import router as basemap_router
from .api.routes_dxf import router as dxf_router
from .api.routes_indoor import router as indoor_router
from .api.routes_projects import router as projects_router
from .api.routes_rf import router as rf_router
from .api.routes_saas import router as saas_router
from .api.routes_terrain import router as terrain_router
from .api.routes_clutter import router as clutter_router
from .api.routes_copilot import router as copilot_router
from .api.routes_lidar import router as lidar_router
from .api.routes_telemetry import router as telemetry_router
from .api.routes_twoway import router as twoway_router

import asyncio  # noqa: E402
import contextlib  # noqa: E402
import time  # noqa: E402


@contextlib.asynccontextmanager
async def _lifespan(app_: FastAPI):
    """Run the telemetry disconnect-sweeper for the app's lifetime: flags
    assets that stop transmitting as RF-disconnects (correlated with predicted
    dead zones)."""
    from .services.telemetry import ENGINE

    async def sweeper():
        while True:
            await asyncio.sleep(5.0)
            try:
                ENGINE.sweep(time.monotonic(), timeout_s=30.0)
            except Exception:
                pass
    task = asyncio.create_task(sweeper())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    lifespan=_lifespan,
    title="AntennaMaster RF Coverage Simulator API",
    description=(
        "Professional RF planning API: global SRTM 30 m terrain fused with "
        "local DXF relief, six propagation models (FSPL, Hata family, 3GPP "
        "TR 38.901), Deygout diffraction, environmental losses (Weissberger "
        "foliage, ITU-R P.838 rain, P.676 gases), measured MSI antenna "
        "patterns, single/multi-site coverage, indoor multi-wall, tunnel "
        "waveguide and through-the-earth studies."
    ),
    version="2.0.0",
    openapi_tags=[
        {"name": "dxf", "description": "DXF upload, layer inventory, "
         "georeferencing (known CRS / Helmert control points / origin+bearing), "
         "hillshade overlays and session state restore."},
        {"name": "terrain", "description": "Fused elevation queries, geodesic "
         "TX→RX profiles with link analysis and technology studies, CSV export."},
        {"name": "rf", "description": "Technology presets, propagation models, "
         "MSI antenna patterns, single-site and multi-site best-server coverage "
         "with PNG/KMZ export."},
        {"name": "indoor-underground", "description": "Floor-plan multi-wall "
         "coverage, material library, tunnel waveguide and through-the-earth "
         "links."},
        {"name": "saas", "description": "Accounts, tiers & entitlements, "
         "project workspaces, CAPEX/OPEX estimates, branded PDF reports, "
         "async jobs, audit log, white-labeling."},
    ],
)

# The Next.js dev server runs on another port; origins are configurable via
# AM_CORS_ORIGINS (comma-separated), defaulting to open for dev setups.
from .config import CORS_ORIGINS  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
# High-sample profile responses are ~330 KB of JSON; gzip cuts them ~8x.
# (PNG responses are already compressed and skip this by content check.)
app.add_middleware(GZipMiddleware, minimum_size=8192)


def _json_safe(value):
    """Recursively replace non-finite floats so a payload can be serialized.

    NaN/Infinity are accepted by Python's JSON parser but are not valid JSON
    to emit, so echoing one back raises "Out of range float values are not
    JSON compliant".
    """
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)                       # "nan" / "inf" / "-inf"
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request, exc: RequestValidationError):
    """Return 422 for an invalid body without echoing what was submitted.

    Two problems with FastAPI's default handler, which reflects the rejected
    value back inside the error detail:

    * **It leaks credentials.** POST /api/auth/register with a 5-character
      password answered `{"input": "<the plaintext password>"}`, which then
      lands in browser devtools, reverse-proxy logs and any client-side error
      reporter.  The same is true of any rejected field.
    * **It can 500.** When the input is NaN or Infinity - which json.loads
      happily accepts on the way in - serializing the *error* raises, turning
      a clean 422 into a stack trace.

    A client needs the location, the type and the message to fix its call; it
    never needs the value it just sent.  Drop `input` and `ctx` (which can
    carry fragments of the value too) and keep the rest.
    """
    safe = [{k: v for k, v in err.items() if k in ("type", "loc", "msg")}
            for err in exc.errors()]
    return JSONResponse(status_code=422,
                        content={"detail": _json_safe(safe)})


def _client_ip(request) -> str | None:
    """Best client IP: first hop of X-Forwarded-For (behind a proxy) else the
    direct peer.  Only the left-most, client-supplied address is used for the
    record; trust it accordingly (it is evidence, not authorization)."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else None


@app.middleware("http")
async def audit_middleware(request, call_next):
    """Centralized OT/IT audit trail: records every critical action (logins,
    uploads, project changes, data exports) with the acting user and client
    IP, to the audit log file and the database."""
    from .services import audit
    action = audit.classify(request.method, request.url.path)
    response = await call_next(request)
    if action is not None and response.status_code < 400:
        # Identity: an endpoint may stamp request.state (e.g. login, where the
        # request carries no token yet); otherwise resolve from the bearer.
        user_id = getattr(request.state, "audit_user_id", None)
        email = getattr(request.state, "audit_email", None)
        if user_id is None:
            auth = request.headers.get("authorization")
            if auth and auth.lower().startswith("bearer "):
                try:
                    from .services.saas import db
                    u = db.user_for_token(auth.split(" ", 1)[1].strip())
                    if u:
                        user_id, email = u.get("id"), u.get("email")
                except Exception:  # noqa: BLE001
                    pass
        detail = getattr(request.state, "audit_detail",
                         f"{request.method} {request.url.path}")
        # An endpoint may declare that its actor must not be named — account
        # erasure records that it happened, under an opaque subject id, with
        # no email and no client IP, or the record would re-create the very
        # personal data the request destroyed.
        subject = getattr(request.state, "audit_subject", None)
        org_name = getattr(request.state, "audit_org", None)
        if subject is not None:
            email, user_id = None, None
        try:
            audit.record(action, user_id=user_id, email=email,
                         ip=None if subject else _client_ip(request),
                         status=response.status_code, detail=detail,
                         subject=subject, org_name=org_name)
        except Exception:  # noqa: BLE001 - auditing must never break a request
            pass
    return response

app.include_router(dxf_router)
app.include_router(terrain_router)
app.include_router(rf_router)
app.include_router(indoor_router)
app.include_router(auth_router)
app.include_router(projects_router)
app.include_router(saas_router)
app.include_router(basemap_router)
app.include_router(twoway_router)
app.include_router(copilot_router)
app.include_router(telemetry_router)
app.include_router(lidar_router)
app.include_router(clutter_router)


@app.get("/api/health")
def health() -> dict:
    """Liveness only: the process is up."""
    return {"status": "ok"}


@app.get("/api/ready")
def ready():
    """Readiness: can this worker actually serve studies?  Verifies the data
    dir is writable and reports (without failing on) DEM cache state, so
    orchestrators can pull broken workers out of rotation."""
    import os

    from fastapi.responses import JSONResponse

    from .config import DATA_DIR, DEM_CACHE_DIR, DSM_URL
    checks = {"data_dir_writable": os.access(DATA_DIR, os.W_OK)}
    checks["dem_cache_present"] = any(DEM_CACHE_DIR.glob("*/*/*.png"))
    checks["surface_model_configured"] = bool(DSM_URL)
    ok = checks["data_dir_writable"]
    return JSONResponse(status_code=200 if ok else 503,
                        content={"status": "ready" if ok else "degraded",
                                 "checks": checks})
