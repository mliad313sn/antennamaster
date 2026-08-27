"""Live telemetry / digital-twin endpoints.

Ingest real-time asset positions (POST or WebSocket) and stream the live twin
state (Server-Sent Events) to the Live Operations dashboard.  A coverage
context ties the moving assets to the RF prediction so dead-zone entries and
RF-disconnect correlations are raised automatically.
"""
from __future__ import annotations

import asyncio
import json
import time

from fastapi import (APIRouter, Depends, HTTPException, Query, Request, WebSocket,
                     WebSocketDisconnect)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.rf.models import MODEL_INFO
from ..services.rf.technologies import get_technology
from ..services import telemetry_store
from ..services.saas.tiers import saas_mode
from .routes_auth import current_user


def tenant_engine(user: dict | None = Depends(current_user),
                  token: str | None = Query(
                      None, description="Bearer token for EventSource clients, "
                                        "which cannot send an Authorization "
                                        "header. Ignored when the header is "
                                        "present.")):
    """The telemetry TENANT this caller is allowed to touch.

    Returns a key, not an engine: the state lives in a shared store so every
    uvicorn worker sees the same fleet (see services/telemetry_store.py).

    Live asset positions are the real-time locations of responders, mine crews
    and field staff - the most sensitive data this product handles. Every
    telemetry route used to be unauthenticated against ONE process-global
    engine, so anybody who could reach the backend could read another
    operator's fleet and inject forged pings into it.

    In SaaS mode a caller must therefore authenticate, and gets an engine
    scoped to their organisation (falling back to their own account when they
    have none). A self-hosted single-tenant deployment keeps the shared
    "local" engine and stays open, exactly as before - the same rule the DXF
    and coverage-result guards already follow.
    """
    if not saas_mode():
        return "local"
    if user is None and token:
        # EventSource has no way to set a header, and the Live Ops dashboard
        # is an SSE client, so the stream accepts the token as a query
        # parameter. Everything else should use the header: a token in a URL
        # ends up in proxy logs and browser history.
        from ..services.saas import db as _db
        user = _db.user_for_token(token.strip())
    if user is None:
        raise HTTPException(401, "Authentication required for telemetry")
    org = (user.get("org_name") or "").strip()
    return f"org:{org}" if org else f"user:{user['id']}"
from .routes_terrain import resolve_fusion

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


class Ping(BaseModel):
    asset_id: str = Field(min_length=1, max_length=80)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    name: str | None = Field(None, max_length=80)


class IngestRequest(BaseModel):
    pings: list[Ping] = Field(min_length=1, max_length=500)


class CoverageContextRequest(BaseModel):
    tx_lat: float = Field(ge=-90, le=90)
    tx_lon: float = Field(ge=-180, le=180)
    technology: str = "custom"
    surface: bool = False
    k_factor: float = Field(4.0 / 3.0, gt=0.1, le=10)
    freq_mhz: float | None = Field(None, gt=0)
    model: str | None = None
    tx_power_dbm: float | None = None
    tx_gain_dbi: float | None = None
    h_bs_m: float | None = Field(None, gt=0)
    h_ut_m: float | None = Field(None, gt=0)


def _build_served_fn(req: CoverageContextRequest):
    """A served-predicate (lat, lon) -> (served, margin_db) from the RF model,
    using the same link budget the planner uses."""
    tech = get_technology(req.technology)
    for f in ("freq_mhz", "model", "tx_power_dbm", "tx_gain_dbi", "h_bs_m", "h_ut_m"):
        v = getattr(req, f)
        if v is not None:
            tech[f] = v
    if tech["model"] not in MODEL_INFO:
        raise HTTPException(422, f"Unknown propagation model: {tech['model']!r}")
    fusion = resolve_fusion(req.surface)
    from ..services.rf.planning import evaluate_receiver

    def served_fn(lat: float, lon: float):
        res = evaluate_receiver(fusion, dict(tech), req.tx_lat, req.tx_lon,
                                lat, lon, k=req.k_factor)
        return bool(res["served"]), float(res["margin_db"])
    return served_fn, tech


def _predicate_from_context(ctx: dict):
    """Rebuild the served-predicate from a stored coverage request.

    Registered with the store so any worker - including one that never
    handled the /coverage-context call - can correlate against the same RF
    prediction after loading the shared state.
    """
    return _build_served_fn(CoverageContextRequest(**ctx))[0]


telemetry_store.set_predicate_factory(_predicate_from_context)


@router.post("/coverage-context")
def set_coverage_context(req: CoverageContextRequest,
                         tenant: str = Depends(tenant_engine)) -> dict:
    """Bind the live twin to an RF coverage prediction (TX + technology) so
    incoming assets are correlated against predicted dead zones."""
    served_fn, tech = _build_served_fn(req)
    # Store the WHOLE request, not a summary: the predicate closes over the
    # terrain service and cannot be serialised, so each worker rebuilds its
    # own from this on load. A summary would rebuild a different predicate.
    ctx = req.model_dump() | {"freq_mhz": tech["freq_mhz"]}
    with telemetry_store.shared(tenant) as eng:
        eng.set_coverage(served_fn, ctx)
        return {"ok": True, "coverage_context": eng.coverage_context}


@router.post("/ingest")
def ingest(req: IngestRequest,
           tenant: str = Depends(tenant_engine)) -> dict:
    """Ingest one or more asset position pings (fleet-management / IoT feed)."""
    # Wall clock, not monotonic: these timestamps cross process boundaries
    # now, and a monotonic epoch is per-process.
    now = time.time()
    with telemetry_store.shared(tenant) as eng:
        updated = [eng.ingest(p.asset_id, p.lat, p.lon, now, p.name)
                   for p in req.pings]
    return {"ingested": len(updated), "assets": updated}


@router.get("/state")
def state(tenant: str = Depends(tenant_engine)) -> dict:
    """Current live-twin snapshot (assets + coverage context + event cursor)."""
    with telemetry_store.shared(tenant, write=False) as eng:
        return eng.snapshot()


@router.get("/events")
def events(since: int = 0,
           tenant: str = Depends(tenant_engine)) -> dict:
    """Correlation events (dead-zone entries, RF disconnects) after ``since``."""
    with telemetry_store.shared(tenant, write=False) as eng:
        return {"events": eng.events_since(since), "event_seq": eng.event_seq}


@router.get("/stream")
async def stream(request: Request,
                 tenant: str = Depends(tenant_engine)) -> StreamingResponse:
    """Server-Sent Events stream of the live twin: a periodic state snapshot
    plus any new correlation events, for the Live Operations dashboard."""
    async def gen():
        cursor = 0
        with telemetry_store.shared(tenant, write=False) as eng:
            yield f"event: state\ndata: {json.dumps(eng.snapshot())}\n\n"
        while True:
            if await request.is_disconnected():
                break
            with telemetry_store.shared(tenant, write=False) as eng:
                new = eng.events_since(cursor)
                cursor = eng.event_seq
                snap = eng.snapshot()
            for e in new:
                yield f"event: correlation\ndata: {json.dumps(e)}\n\n"
            yield f"event: state\ndata: {json.dumps(snap)}\n\n"
            await asyncio.sleep(1.0)
    return StreamingResponse(
        gen(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache",
                 # Do not let a proxy buffer the stream...
                 "X-Accel-Buffering": "no",
                 # ...and do not let OUR OWN gzip middleware buffer it either.
                 # Browsers always advertise gzip, so GZipMiddleware wrapped
                 # this response and held every frame waiting for a stream
                 # that never ends: Live Operations was permanently blank in
                 # every real browser while `curl` (which does not ask for
                 # gzip by default) worked perfectly. Worse, the connection
                 # SUCCEEDS, so EventSource never fires onerror and the
                 # polling fallback never engaged. Declaring the encoding
                 # up front makes the compressor skip it.
                 "Content-Encoding": "identity"})


@router.websocket("/ws")
async def ingest_ws(ws: WebSocket) -> None:
    """WebSocket ingest for high-rate FMS/IoT feeds: each JSON message is a
    ping ``{asset_id, lat, lon, name?}``; the server echoes the updated asset."""
    # A WebSocket cannot use the HTTP dependency, so resolve the tenant by
    # hand from the same bearer token: in SaaS mode an unauthenticated socket
    # is closed with 1008 (policy violation) rather than silently accepted
    # into someone else's fleet.
    token = ws.query_params.get("token") or ""
    if not token:
        auth = ws.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1].strip()
    if saas_mode():
        from ..services.saas import db as _db
        user = _db.user_for_token(token) if token else None
        if user is None:
            await ws.close(code=1008)
            return
        org = (user.get("org_name") or "").strip()
        tenant = f"org:{org}" if org else f"user:{user['id']}"
    else:
        tenant = "local"

    await ws.accept()
    try:
        while True:
            msg = await ws.receive_json()
            try:
                p = Ping(**msg)
            except Exception as exc:  # malformed ping -> report, keep the socket
                await ws.send_json({"error": str(exc)})
                continue
            with telemetry_store.shared(tenant) as eng:
                updated = eng.ingest(p.asset_id, p.lat, p.lon, time.time(),
                                     p.name)
            await ws.send_json({"ok": True, "asset": updated})
    except WebSocketDisconnect:
        return
