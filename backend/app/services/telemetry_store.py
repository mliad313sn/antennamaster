"""Cross-worker storage for the live-telemetry twin.

The engine in ``telemetry.py`` keeps its registry in a module-level dict, which
is invisible to sibling uvicorn workers — and the documented launch path runs
**two** of them. So a ping ingested by worker A was simply absent when worker B
served the next `/state` read, and the Live Operations dashboard showed a fleet
that flickered in and out of existence. Measured on the running stack: eight
consecutive reads after a single ingest returned 2, 1, 2, 2, 2, 2, 2, 2 assets.

``results_store`` already learned this lesson for rasters and says so in its
own docstring ("invisible to sibling uvicorn workers"); telemetry was left
behind. This is the same fix: one shared place, so every worker sees the same
world.

TWO THINGS THAT HAD TO CHANGE TOGETHER

* **Where the state lives.** SQLite (WAL), one row per tenant holding the whole
  twin as JSON. The data is small — tens of assets, a 50-point track each, a
  500-event ring — and the ingest endpoint takes a *batch* of pings, so this is
  one transaction per request, not per ping.

* **Which clock stamps it.** The engine was fed ``time.monotonic()``, whose
  epoch is arbitrary and *per process*. Sharing those numbers between workers
  would make an asset look either impossibly stale or stale in the future, so
  the disconnect sweep would fire at random. Persisted timestamps are wall
  clock. Monotonic was the right choice while the state never left the
  process; it stops being right the moment it does.

The RF predicate cannot be serialised — it closes over the terrain service — so
what is stored is the coverage *request* that produced it, and each worker
rebuilds its own predicate from that on load. The factory is injected by the
route layer to keep this module free of API imports.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager

from ..config import DATA_DIR
from .telemetry import MAX_EVENTS, MAX_TRACK, Asset, TelemetryEngine

DB_PATH = DATA_DIR / "telemetry.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS telemetry_state (
    tenant     TEXT PRIMARY KEY,
    state_json TEXT NOT NULL,
    updated_at REAL NOT NULL
);
"""

# Rebuilds the served-predicate from a stored coverage request. Injected by
# routes_telemetry so this module never imports the API layer.
_predicate_factory = None
# Per-process memo: building the predicate resolves the terrain service, so it
# is worth not doing on every single read.
_predicates: dict[str, object] = {}
_predicates_lock = threading.Lock()

_init_done = False
_init_lock = threading.Lock()


def set_predicate_factory(fn) -> None:
    """Register how to turn a stored coverage request back into a predicate."""
    global _predicate_factory
    _predicate_factory = fn


def _connect() -> sqlite3.Connection:
    global _init_done
    conn = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=8000")
    if not _init_done:
        with _init_lock:
            conn.executescript(_SCHEMA)
            _init_done = True
    return conn


# ------------------------------------------------------------ (de)serialise
def _dump(eng: TelemetryEngine) -> str:
    return json.dumps({
        "assets": [{"asset_id": a.asset_id, "lat": a.lat, "lon": a.lon,
                    "name": a.name, "last_seen": a.last_seen,
                    "transmitting": a.transmitting,
                    "in_dead_zone": a.in_dead_zone, "margin_db": a.margin_db,
                    "track": list(a.track)}
                   for a in eng.assets.values()],
        "events": list(eng._events)[-MAX_EVENTS:],
        "seq": eng._seq,
        "coverage_context": eng.coverage_context,
    }, separators=(",", ":"))


def _load(eng: TelemetryEngine, raw: str | None) -> None:
    eng.reset()
    if not raw:
        return
    try:
        state = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return                      # a corrupt row starts an empty world
    from collections import deque
    for d in state.get("assets", []):
        a = Asset(asset_id=d["asset_id"], lat=d["lat"], lon=d["lon"],
                  name=d.get("name", ""), last_seen=d.get("last_seen", 0.0),
                  transmitting=d.get("transmitting", True),
                  in_dead_zone=d.get("in_dead_zone", False),
                  margin_db=d.get("margin_db"))
        a.track = deque(d.get("track", []), maxlen=MAX_TRACK)
        eng.assets[a.asset_id] = a
    eng._events = deque(state.get("events", []), maxlen=MAX_EVENTS)
    eng._seq = int(state.get("seq", 0))

    ctx = state.get("coverage_context")
    if ctx:
        eng.coverage_context = ctx
        eng._served_fn = _predicate_for(ctx)


def _predicate_for(ctx: dict):
    """This worker's predicate for a stored coverage request, memoised."""
    if _predicate_factory is None:
        return None
    key = json.dumps(ctx, sort_keys=True, separators=(",", ":"))
    with _predicates_lock:
        hit = _predicates.get(key)
    if hit is not None:
        return hit
    try:
        fn = _predicate_factory(ctx)
    except Exception:                      # a stale/invalid context must not
        return None                        # break every telemetry read
    with _predicates_lock:
        if len(_predicates) > 32:          # bounded: contexts are rebound rarely
            _predicates.clear()
        _predicates[key] = fn
    return fn


# ------------------------------------------------------------------ access
@contextmanager
def shared(tenant: str, write: bool = True):
    """Yield this tenant's engine, loaded from and (when writing) saved to the
    shared store under a transaction.

    Reads deliberately do NOT take the write lock: the SSE stream snapshots
    once a second per connected client, and serialising those behind an
    exclusive transaction would make the dashboard the slowest thing on the
    box.
    """
    conn = _connect()
    try:
        if write:
            conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT state_json FROM telemetry_state WHERE tenant=?",
            (tenant,)).fetchone()
        eng = TelemetryEngine()
        _load(eng, row[0] if row else None)
        try:
            yield eng
        except Exception:
            if write:
                conn.execute("ROLLBACK")
            raise
        if write:
            conn.execute(
                "INSERT INTO telemetry_state (tenant, state_json, updated_at) "
                "VALUES (?,?,?) ON CONFLICT(tenant) DO UPDATE SET "
                "state_json=excluded.state_json, updated_at=excluded.updated_at",
                (tenant, _dump(eng), time.time()))
            conn.execute("COMMIT")
    finally:
        conn.close()


def tenants() -> list[str]:
    """Every tenant with live state — what the disconnect sweeper iterates."""
    conn = _connect()
    try:
        return [r[0] for r in conn.execute(
            "SELECT tenant FROM telemetry_state").fetchall()]
    finally:
        conn.close()


def reset() -> None:
    """Drop all live state (tests, and a manual escape hatch)."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM telemetry_state")
    finally:
        conn.close()
    with _predicates_lock:
        _predicates.clear()
