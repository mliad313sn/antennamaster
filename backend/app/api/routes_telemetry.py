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

from fastapi import (APIRouter, Depends, HTTPException, Request, WebSocket,
                     WebSocketDisconnect)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.rf.models import MODEL_INFO
from ..services.rf.technologies import get_technology
from ..services.telemetry import ENGINE
from .routes_auth import current_user
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


@router.post("/coverage-context")
def set_coverage_context(req: CoverageContextRequest,
                         user: dict | None = Depends(current_user)) -> dict:
    """Bind the live twin to an RF coverage prediction (TX + technology) so
    incoming assets are correlated against predicted dead zones."""
    served_fn, tech = _build_served_fn(req)
    ENGINE.set_coverage(served_fn, {
        "tx_lat": req.tx_lat, "tx_lon": req.tx_lon,
        "technology": req.technology, "freq_mhz": tech["freq_mhz"]})
    return {"ok": True, "coverage_context": ENGINE.coverage_context}


@router.post("/ingest")
def ingest(req: IngestRequest) -> dict:
    """Ingest one or more asset position pings (fleet-management / IoT feed)."""
    now = time.monotonic()
    updated = [ENGINE.ingest(p.asset_id, p.lat, p.lon, now, p.name)
               for p in req.pings]
    return {"ingested": len(updated), "assets": updated}


@router.get("/state")
def state() -> dict:
    """Current live-twin snapshot (assets + coverage context + event cursor)."""
    return ENGINE.snapshot()


@router.get("/events")
def events(since: int = 0) -> dict:
    """Correlation events (dead-zone entries, RF disconnects) after ``since``."""
    return {"events": ENGINE.events_since(since), "event_seq": ENGINE.event_seq}


@router.get("/stream")
async def stream(request: Request) -> StreamingResponse:
    """Server-Sent Events stream of the live twin: a periodic state snapshot
    plus any new correlation events, for the Live Operations dashboard."""
    async def gen():
        cursor = 0
        # Prime with the current state so a new client renders immediately.
        yield f"event: state\ndata: {json.dumps(ENGINE.snapshot())}\n\n"
        while True:
            if await request.is_disconnected():
                break
            new = ENGINE.events_since(cursor)
            cursor = ENGINE.event_seq
            for e in new:
                yield f"event: correlation\ndata: {json.dumps(e)}\n\n"
            yield f"event: state\ndata: {json.dumps(ENGINE.snapshot())}\n\n"
            await asyncio.sleep(1.0)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.websocket("/ws")
async def ingest_ws(ws: WebSocket) -> None:
    """WebSocket ingest for high-rate FMS/IoT feeds: each JSON message is a
    ping ``{asset_id, lat, lon, name?}``; the server echoes the updated asset."""
    await ws.accept()
    try:
        while True:
            msg = await ws.receive_json()
            try:
                p = Ping(**msg)
            except Exception as exc:  # malformed ping -> report, keep the socket
                await ws.send_json({"error": str(exc)})
                continue
            updated = ENGINE.ingest(p.asset_id, p.lat, p.lon, time.monotonic(),
                                    p.name)
            await ws.send_json({"ok": True, "asset": updated})
    except WebSocketDisconnect:
        return
