"""Measured antenna pattern support: MSI Planet (.msi / .pln / .ant) files.

The MSI Planet format is the de-facto exchange format vendors (Kathrein,
CommScope, Huawei, ...) publish for base-station antennas:

    NAME    K742265
    GAIN    17.8 dBi
    TILT    ELECTRICAL 2
    HORIZONTAL 360
    0 0.0
    1 0.1
    ...                  <- attenuation (dB below peak) per degree
    VERTICAL 360
    ...

When a pattern is attached to a coverage study its horizontal + vertical
attenuations replace the parametric sector model, so the simulation uses the
antenna the site will actually be built with.  Patterns are persisted under
DATA_DIR/antennas so any worker can serve them and restarts lose nothing.
"""
from __future__ import annotations

import json
import re
import threading
import uuid

import numpy as np

from ...config import DATA_DIR

ANTENNA_DIR = DATA_DIR / "antennas"
ANTENNA_DIR.mkdir(parents=True, exist_ok=True)

_mem: dict[str, dict] = {}
_lock = threading.Lock()

_HEADER_RE = re.compile(r"^\s*([A-Z_]+)\s+(.*?)\s*$", re.IGNORECASE)


def parse_msi(text: str) -> dict:
    """Parse an MSI Planet pattern file into a normalized dict.

    Returns {name, gain_dbi, electrical_tilt_deg, horizontal[360],
    vertical[360]} with attenuations in dB below peak, index = degree.
    Raises ValueError on files without both 360-point patterns.
    """
    name = "unnamed"
    gain_dbi: float | None = None
    tilt = 0.0
    horizontal: list[float] | None = None
    vertical: list[float] | None = None

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        m = _HEADER_RE.match(line)
        key = m.group(1).upper() if m else ""
        val = m.group(2) if m else ""

        if key == "NAME":
            name = val
        elif key == "GAIN":
            gm = re.match(r"(-?\d+(?:\.\d+)?)\s*(dBd|dBi)?", val, re.IGNORECASE)
            if gm:
                g = float(gm.group(1))
                unit = (gm.group(2) or "dBd").lower()
                # MSI files default to dBd; convert to dBi.
                gain_dbi = g + 2.15 if unit == "dbd" else g
        elif key == "TILT":
            tm = re.search(r"(-?\d+(?:\.\d+)?)", val)
            if tm:
                tilt = float(tm.group(1))
        elif key in ("HORIZONTAL", "VERTICAL"):
            count = int(float(val)) if val.strip() else 360
            pts: list[tuple[float, float]] = []
            while i < len(lines) and len(pts) < count:
                row = lines[i].strip()
                i += 1
                if not row:
                    continue
                parts = row.replace(",", " ").split()
                if len(parts) < 2:
                    continue
                try:
                    pts.append((float(parts[0]), float(parts[1])))
                except ValueError:
                    continue
            # Resample onto integer degrees 0..359 (files are usually already
            # per-degree, but some use fractional or sparse angles).
            angles = np.array([p[0] % 360 for p in pts])
            attens = np.array([abs(p[1]) for p in pts])   # attenuation, dB down
            order = np.argsort(angles)
            grid = np.interp(np.arange(360), angles[order], attens[order],
                             period=360)
            if key == "HORIZONTAL":
                horizontal = grid.tolist()
            else:
                vertical = grid.tolist()

    if horizontal is None or vertical is None:
        raise ValueError("MSI file must contain both HORIZONTAL and VERTICAL "
                         "360-point patterns")
    return {
        "name": name,
        "gain_dbi": gain_dbi if gain_dbi is not None else 0.0,
        "electrical_tilt_deg": tilt,
        "horizontal": horizontal,
        "vertical": vertical,
    }


# ------------------------------------------------------------------- store
def save_antenna(text: str, owner_id: int | None = None) -> dict:
    """Parse + persist a pattern; returns metadata including its id.
    ``owner_id`` scopes the pattern to its uploader in listings."""
    pattern = parse_msi(text)
    pattern["owner_id"] = owner_id
    antenna_id = uuid.uuid4().hex[:12]
    (ANTENNA_DIR / f"{antenna_id}.json").write_text(json.dumps(pattern))
    with _lock:
        _mem[antenna_id] = pattern
    return {"antenna_id": antenna_id, "name": pattern["name"],
            "gain_dbi": pattern["gain_dbi"],
            "electrical_tilt_deg": pattern["electrical_tilt_deg"],
            "h_beamwidth_deg": _beamwidth(pattern["horizontal"]),
            "v_beamwidth_deg": _beamwidth(pattern["vertical"])}


class AntennaAccessError(PermissionError):
    """Raised when a caller requests another tenant's private pattern."""


def load_antenna(antenna_id: str, owner_id: int | None = None) -> dict | None:
    """Load a pattern by id, enforcing owner scoping.

    A pattern with a non-null ``owner_id`` is private: only its owner may
    load it (mirrors ``list_antennas``' visibility rule).  Passing the
    wrong/no owner for a private pattern raises ``AntennaAccessError`` so
    the API can answer 403 instead of leaking the model.  ``None``-owner
    (anonymous / open-mode) patterns stay readable by anyone.
    """
    with _lock:
        hit = _mem.get(antenna_id)
    if hit is None:
        path = ANTENNA_DIR / f"{''.join(c for c in antenna_id if c.isalnum())}.json"
        if not path.exists():
            return None
        hit = json.loads(path.read_text())
        with _lock:
            _mem[antenna_id] = hit
    pat_owner = hit.get("owner_id")
    if pat_owner is not None and pat_owner != owner_id:
        raise AntennaAccessError("This antenna pattern belongs to another account")
    return hit


def list_antennas(owner_id: int | None = None) -> list[dict]:
    """Patterns visible to the caller: their own uploads plus ownerless
    (anonymous/open-mode) patterns.  One tenant's proprietary antenna
    models must never appear in another tenant's dropdown."""
    out = []
    for path in sorted(ANTENNA_DIR.glob("*.json")):
        try:
            p = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        pat_owner = p.get("owner_id")
        if pat_owner is not None and pat_owner != owner_id:
            continue
        out.append({"antenna_id": path.stem, "name": p.get("name", "?"),
                    "gain_dbi": p.get("gain_dbi", 0.0),
                    "h_beamwidth_deg": _beamwidth(p.get("horizontal", [])),
                    "v_beamwidth_deg": _beamwidth(p.get("vertical", []))})
    return out


def _beamwidth(pattern: list[float]) -> float:
    """-3 dB beamwidth of a 360-point attenuation pattern (0 if flat)."""
    if len(pattern) != 360:
        return 0.0
    below = np.asarray(pattern) <= 3.0
    return float(np.count_nonzero(below))


def pattern_attenuation(pattern: dict, az_off_deg: np.ndarray,
                        elev_off_deg: np.ndarray) -> np.ndarray:
    """Total pattern attenuation (dB >= 0) at the given horizontal offsets
    from boresight azimuth and vertical offsets from boresight elevation.

    Uses the standard sum-of-cuts approximation (H(az) + V(el), capped at
    the deepest measured null) common to planning tools.
    """
    h = np.asarray(pattern["horizontal"])
    v = np.asarray(pattern["vertical"])
    az_idx = np.round(np.asarray(az_off_deg) % 360).astype(int) % 360
    el_idx = np.round(np.asarray(elev_off_deg) % 360).astype(int) % 360
    total = h[az_idx] + v[el_idx]
    cap = max(float(h.max()), float(v.max()))
    return np.minimum(total, cap)
