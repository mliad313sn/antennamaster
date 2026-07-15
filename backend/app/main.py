"""FastAPI application entry point.

Run locally with:
    uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
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

app = FastAPI(
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
        try:
            audit.record(action, user_id=user_id, email=email,
                         ip=_client_ip(request), status=response.status_code,
                         detail=detail)
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
