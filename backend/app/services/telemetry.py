"""Live telemetry / digital-twin engine.

Ingests real-time location pings from fleet-management systems or IoT trackers
and correlates each asset's position against the platform's own RF coverage
prediction — the bridge from a static planning tool to a live digital twin.

Two correlations make it operational, not just a moving-dot map:

  * DEAD-ZONE ENTRY — when an asset moves into a predicted no-coverage area
    (evaluated against the configured TX + technology via the same link-budget
    the planner uses), it is flagged so the UI can flash it yellow.
  * RF-DISCONNECT CORRELATION — when an asset stops transmitting, the engine
    logs the event *and* whether its last known position was inside a predicted
    dead zone, turning "we lost the tracker" into "we lost it exactly where the
    RF model said we would".

The core (ingest / sweep / snapshot) is synchronous and framework-agnostic:
the coverage predicate is injected, and staleness is evaluated against a caller-
supplied ``now`` (monotonic seconds), so it is fully deterministic under test.
The async SSE/WebSocket plumbing lives in the route layer.
"""
from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

# A served-predicate maps (lat, lon) -> (served: bool, margin_db: float).
ServedFn = Callable[[float, float], "tuple[bool, float]"]

MAX_TRACK = 50          # positions retained per asset
MAX_EVENTS = 500        # ring buffer of correlation events
# How long an asset may be silent before it leaves the live twin. Far longer
# than the 30 s disconnect threshold on purpose - see TelemetryEngine.sweep.
RETIRE_AFTER_S = 3600.0


@dataclass
class Asset:
    asset_id: str
    lat: float
    lon: float
    name: str = ""
    last_seen: float = 0.0          # monotonic seconds at last ping
    transmitting: bool = True
    in_dead_zone: bool = False
    margin_db: float | None = None
    track: deque = field(default_factory=lambda: deque(maxlen=MAX_TRACK))

    def as_dict(self) -> dict:
        return {"asset_id": self.asset_id, "lat": self.lat, "lon": self.lon,
                "name": self.name, "transmitting": self.transmitting,
                "in_dead_zone": self.in_dead_zone, "margin_db": self.margin_db,
                "last_seen": round(self.last_seen, 2),
                "track": list(self.track)}


class TelemetryEngine:
    """Thread-safe in-memory registry of live assets + correlation events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.assets: dict[str, Asset] = {}
        self._events: deque = deque(maxlen=MAX_EVENTS)
        self._seq = 0
        self._served_fn: ServedFn | None = None
        self.coverage_context: dict | None = None

    # ---------------------------------------------------------- coverage ctx
    def set_coverage(self, served_fn: ServedFn | None, context: dict | None) -> None:
        with self._lock:
            self._served_fn = served_fn
            self.coverage_context = context

    # --------------------------------------------------------------- events
    def _emit(self, etype: str, asset: Asset, now: float, **extra) -> None:
        self._seq += 1
        self._events.append({
            "seq": self._seq, "type": etype, "asset_id": asset.asset_id,
            "name": asset.name, "lat": asset.lat, "lon": asset.lon,
            "at": round(now, 2), **extra})

    def events_since(self, cursor: int) -> list[dict]:
        with self._lock:
            return [e for e in self._events if e["seq"] > cursor]

    @property
    def event_seq(self) -> int:
        return self._seq

    # --------------------------------------------------------------- ingest
    def ingest(self, asset_id: str, lat: float, lon: float, now: float,
               name: str | None = None) -> dict:
        """Record a position ping; evaluate coverage; emit transition events."""
        with self._lock:
            a = self.assets.get(asset_id)
            if a is None:
                a = Asset(asset_id=asset_id, lat=lat, lon=lon, name=name or asset_id)
                self.assets[asset_id] = a
                self._emit("asset_online", a, now)
            was_transmitting = a.transmitting
            a.lat, a.lon = lat, lon
            if name:
                a.name = name
            a.last_seen = now
            a.transmitting = True
            a.track.append([round(lat, 6), round(lon, 6)])
            if not was_transmitting:
                self._emit("asset_reconnect", a, now)

            # Dead-zone correlation against the configured coverage prediction.
            if self._served_fn is not None:
                served, margin = self._served_fn(lat, lon)
                a.margin_db = round(float(margin), 1)
                now_dead = not served
                if now_dead and not a.in_dead_zone:
                    self._emit("enter_dead_zone", a, now, margin_db=a.margin_db)
                elif not now_dead and a.in_dead_zone:
                    self._emit("exit_dead_zone", a, now, margin_db=a.margin_db)
                a.in_dead_zone = now_dead
            return a.as_dict()

    # ---------------------------------------------------------------- sweep
    def sweep(self, now: float, timeout_s: float = 30.0,
              retire_after_s: float = RETIRE_AFTER_S) -> list[dict]:
        """Mark assets that have not pinged within ``timeout_s`` as no longer
        transmitting and log an RF-disconnect correlation event (with whether
        the last position was a predicted dead zone).  Returns new events.

        Assets silent for ``retire_after_s`` leave the live twin entirely.
        The two thresholds answer different questions and cannot be one
        number: 30 s means "this radio just dropped", which an operator needs
        to see immediately and which is the whole point of the correlation;
        an hour means "this is not part of the live fleet any more".

        Retiring did not matter while the twin lived in a process and a
        restart emptied it. It does now that the state is shared and durable:
        without it the fleet list is every vehicle that ever pinged, grey
        forever, and the panel an operator scans during an incident fills
        with things that stopped mattering days ago. The disconnect stays in
        the event log, which is the record; the asset list is the *live*
        picture, and a radio silent for an hour is not in it.
        """
        with self._lock:
            fired: list[dict] = []
            for a in self.assets.values():
                if a.transmitting and (now - a.last_seen) > timeout_s:
                    a.transmitting = False
                    self._emit("rf_disconnect", a, now,
                               in_dead_zone=a.in_dead_zone,
                               last_margin_db=a.margin_db,
                               correlation=("predicted-dead-zone" if a.in_dead_zone
                                            else "coverage-was-ok"))
                    fired.append(self._events[-1])
            if retire_after_s > 0:
                for aid in [aid for aid, a in self.assets.items()
                            if (now - a.last_seen) > retire_after_s]:
                    del self.assets[aid]
            return fired

    # ------------------------------------------------------------- snapshot
    def snapshot(self) -> dict:
        with self._lock:
            return {"assets": [a.as_dict() for a in self.assets.values()],
                    "coverage_context": self.coverage_context,
                    "event_seq": self._seq}

    def reset(self) -> None:
        with self._lock:
            self.assets.clear()
            self._events.clear()
            self._seq = 0
            self._served_fn = None
            self.coverage_context = None


# Process-wide singleton: the live-operations state of the DEFAULT tenant,
# which is the only one a self-hosted single-tenant deployment ever uses.
ENGINE = TelemetryEngine()

# One engine per tenant.  Live asset positions are among the most sensitive
# data this product touches - they are the real-time locations of responders,
# mine crews and field staff - so in multi-tenant mode they must not share a
# registry.  A single global engine meant any caller could read another
# operator's fleet and inject forged pings into it.
_ENGINES: dict[str, TelemetryEngine] = {"local": ENGINE}
_ENGINES_LOCK = threading.Lock()


def engine_for(tenant: str) -> TelemetryEngine:
    """The telemetry engine for one tenant, created on first use.

    ``"local"`` is the shared engine used by anonymous/self-hosted
    deployments, so single-tenant behaviour is exactly as it was.
    """
    with _ENGINES_LOCK:
        eng = _ENGINES.get(tenant)
        if eng is None:
            eng = _ENGINES[tenant] = TelemetryEngine()
        return eng


def reset_engines() -> None:
    """Drop every non-default tenant engine (tests)."""
    with _ENGINES_LOCK:
        _ENGINES.clear()
        _ENGINES["local"] = ENGINE
