"""Disk-backed store for simulation results (coverage rasters, heatmaps).

Module-level dicts do not survive process restarts and are invisible to
sibling uvicorn workers - a coverage PNG computed by worker A would 404 when
worker B serves the GET.  This store writes each result as two files under
RESULTS_DIR (<id>.png + <id>.json metadata) so ANY worker can serve ANY
result, restarts lose nothing, and a small in-process cache keeps the hot
path fast.  Old results are pruned by count (oldest mtime first).
"""
from __future__ import annotations

import json
import threading
from collections import OrderedDict
from pathlib import Path

from ..config import RESULTS_DIR

_MAX_RESULTS = 200
# In-process hot cache is LRU-bounded: each entry holds a full raster PNG,
# so an unbounded dict is a slow per-worker memory leak.
_MEM_CAP = 32
_mem: "OrderedDict[str, tuple[bytes, dict]]" = OrderedDict()
_lock = threading.Lock()


def _paths(result_id: str, kind: str) -> tuple[Path, Path]:
    safe = "".join(c for c in result_id if c.isalnum())
    base = RESULTS_DIR / f"{kind}-{safe}"
    return base.with_suffix(".png"), base.with_suffix(".json")


def _mem_put(key: str, value: tuple[bytes, dict]) -> None:
    with _lock:
        _mem[key] = value
        _mem.move_to_end(key)
        while len(_mem) > _MEM_CAP:
            _mem.popitem(last=False)


def save(kind: str, result_id: str, png: bytes, meta: dict) -> None:
    png_path, meta_path = _paths(result_id, kind)
    png_path.write_bytes(png)
    meta_path.write_text(json.dumps(meta))
    _mem_put(f"{kind}-{result_id}", (png, meta))
    _prune()


def load(kind: str, result_id: str) -> tuple[bytes, dict] | None:
    key = f"{kind}-{result_id}"
    with _lock:
        hit = _mem.get(key)
        if hit is not None:
            _mem.move_to_end(key)
    if hit is not None:
        return hit
    png_path, meta_path = _paths(result_id, kind)
    if not png_path.exists():
        return None
    png = png_path.read_bytes()
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    _mem_put(key, (png, meta))
    return png, meta


def _prune() -> None:
    """Keep at most _MAX_RESULTS result pairs on disk (oldest removed)."""
    pngs = sorted(RESULTS_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime)
    excess = len(pngs) - _MAX_RESULTS
    for p in pngs[:max(excess, 0)]:
        p.unlink(missing_ok=True)
        p.with_suffix(".json").unlink(missing_ok=True)
