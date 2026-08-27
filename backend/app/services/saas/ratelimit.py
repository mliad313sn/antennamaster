"""Abuse limits on the expensive endpoints.

A coverage study is seconds of CPU over a numpy grid plus a burst of DEM tile
fetches, and until now anyone who could reach the backend could ask for one in
a loop, unauthenticated, forever. On a public deployment that is a free
denial-of-service against every paying tenant on the same box: no queue, no
quota, no throttle, and the DEM cache filling from someone else's bounding
boxes. Uploads are the same story with disk instead of CPU (100 MB per DXF).

Design choices worth stating:

* **Sliding window, not a fixed one.** A fixed window lets a caller spend the
  whole budget in the last second of one window and again in the first second
  of the next — a 2x burst exactly when the box is already loaded.
* **Keyed by account when there is one, by client IP otherwise.** Keying on
  the bearer token alone would be a bypass: an attacker sends a different
  garbage token per request and gets a fresh bucket each time. A token that
  does not resolve falls back to the IP.
* **In-process.** Per-worker state undercounts by the worker count, which is
  the right failure direction for a limit whose job is to stop a runaway
  loop rather than to bill precisely. A multi-node deployment behind a
  reverse proxy should also set a limit there; this is the floor, not the
  ceiling.
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque

# (limit, window_seconds) per class, for anonymous and authenticated callers.
# Generous enough that a self-hosted engineer working normally never sees
# them, tight enough to stop a loop.
LIMITS: dict[str, dict[str, tuple[int, float]]] = {
    # Heavy numpy + DEM work: coverage rasters, batch, site search, Monte
    # Carlo, async jobs.
    "compute": {"anon": (20, 60.0), "auth": (60, 60.0)},
    # Disk-consuming uploads: DXF (up to 100 MB), antenna patterns, logos.
    "upload": {"anon": (5, 3600.0), "auth": (40, 3600.0)},
}

_hits: dict[tuple[str, str], deque[float]] = {}
_lock = threading.Lock()
_MAX_KEYS = 20_000          # bound the tracking dict itself


def enabled() -> bool:
    """`AM_RATE_LIMIT=0` turns the limits off — for an air-gapped install
    where the only caller is the one engineer running the box."""
    return os.environ.get("AM_RATE_LIMIT", "1") != "0"


def _limit_for(kind: str, authenticated: bool) -> tuple[int, float]:
    conf = LIMITS[kind]
    limit, window = conf["auth" if authenticated else "anon"]
    override = os.environ.get(f"AM_RATE_{kind.upper()}_PER_MIN")
    if override:
        try:
            per_min = max(1, int(override))
        except ValueError:
            return limit, window
        # Express the override in the class's own window so the semantics of
        # "per minute" survive an hourly bucket.
        return max(1, int(per_min * window / 60.0)), window
    return limit, window


def check(kind: str, identity: str, authenticated: bool,
          now: float | None = None) -> float | None:
    """Record one request; return the seconds to wait if it is over budget.

    Returning the wait rather than raising keeps this usable from a
    middleware, a dependency or a test without importing FastAPI here.
    """
    if not enabled():
        return None
    now = time.time() if now is None else now
    limit, window = _limit_for(kind, authenticated)
    key = (kind, identity)
    with _lock:
        if len(_hits) > _MAX_KEYS:
            _hits.clear()               # cheap reset beats unbounded growth
        stamps = _hits.setdefault(key, deque())
        while stamps and now - stamps[0] > window:
            stamps.popleft()
        if len(stamps) >= limit:
            # The oldest hit is what has to age out before there is room.
            return max(0.0, window - (now - stamps[0]))
        stamps.append(now)
        return None


def reset() -> None:
    """Drop all counters (tests; also a manual escape hatch)."""
    with _lock:
        _hits.clear()
