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
from pathlib import Path

from ..config import RESULTS_DIR

_MAX_RESULTS = 200
_mem: dict[str, tuple[bytes, dict]] = {}
_lock = threading.Lock()


def _paths(result_id: str, kind: str) -> tuple[Path, Path]:
    safe = "".join(c for c in result_id if c.isalnum())
    base = RESULTS_DIR / f"{kind}-{safe}"
    return base.with_suffix(".png"), base.with_suffix(".json")


def save(kind: str, result_id: str, png: bytes, meta: dict) -> None:
    png_path, meta_path = _paths(result_id, kind)
    png_path.write_bytes(png)
    meta_path.write_text(json.dumps(meta))
    with _lock:
        _mem[f"{kind}-{result_id}"] = (png, meta)
    _prune()


def load(kind: str, result_id: str) -> tuple[bytes, dict] | None:
    key = f"{kind}-{result_id}"
    with _lock:
        hit = _mem.get(key)
    if hit is not None:
        return hit
    png_path, meta_path = _paths(result_id, kind)
    if not png_path.exists():
        return None
    png = png_path.read_bytes()
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    with _lock:
        _mem[key] = (png, meta)
    return png, meta


def _prune() -> None:
    """Keep at most _MAX_RESULTS result pairs on disk (oldest removed)."""
    pngs = sorted(RESULTS_DIR.glob("*.png"), key=lambda p: p.stat().st_mtime)
    excess = len(pngs) - _MAX_RESULTS
    for p in pngs[:max(excess, 0)]:
        p.unlink(missing_ok=True)
        p.with_suffix(".json").unlink(missing_ok=True)
