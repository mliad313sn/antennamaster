"""Subject access (GDPR art. 15) and erasure (art. 17) for an account.

Erasure is only meaningful if it reaches *everything* the account left
behind, and in this product the account row is the small part: the personal
data of value is in what the user uploaded and computed — site CAD drawings
that give away a customer's floor plan, coverage rasters that give away where
their assets are, proprietary antenna patterns, a white-label logo.  Deleting
the user row alone would leave all of that on the data volume, still owner-
tagged with an id that will be reissued to the next account (SQLite reuses
AUTOINCREMENT ids only after a vacuum, but nothing guarantees it will not).

So both operations enumerate the same owner-tagged stores as the access
guards do — DXF drawings, antenna patterns, rendered rasters, the logo, plus
the database rows (projects and model calibrations) that cascade off the user
— and the export mirrors the erasure: whatever erasure destroys, the export
must have been able to hand over first.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from ...config import DATA_DIR, DXF_STORE_DIR, RESULTS_DIR
from . import db

ANTENNA_DIR = DATA_DIR / "antennas"
LOGO_DIR = DATA_DIR / "logos"


def _json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _owned_results(user_id: int) -> list[tuple[str, dict]]:
    """(stem, meta) for every stored raster this account owns.

    The stem carries the ``<kind>-<id>`` prefix used by ``results_store``, so
    the caller can delete or describe the whole family of sidecars.
    """
    out = []
    for meta_path in sorted(RESULTS_DIR.glob("*.json")):
        meta = _json(meta_path)
        if meta.get("owner_id") == user_id:
            out.append((meta_path.stem, meta))
    return out


def _owned_dxf(user_id: int) -> list[tuple[str, dict]]:
    out = []
    for state in sorted(DXF_STORE_DIR.glob("*.state.json")):
        data = _json(state)
        if data.get("owner_id") == user_id:
            # "<id>.state.json" -> "<id>"
            out.append((state.name[: -len(".state.json")], data))
    return out


def _owned_antennas(user_id: int) -> list[tuple[str, dict]]:
    out = []
    for path in sorted(ANTENNA_DIR.glob("*.json")):
        data = _json(path)
        if data.get("owner_id") == user_id:
            out.append((path.stem, data))
    return out


def export_account(user: dict) -> dict:
    """Everything the platform holds about this account, as portable JSON.

    Art. 20 asks for a "structured, commonly used, machine-readable format",
    which is also the useful format here: the projects come out with their
    full study payloads, so this doubles as a backup a customer can restore
    from or hand to another tool.  Binary blobs (DXF, rasters, logo) are
    listed rather than inlined — they are megabytes each and every one of
    them is downloadable through its own endpoint while the account lives.
    """
    uid = user["id"]
    return {
        "generated_at": time.time(),
        "format": "antennamaster.account-export/1",
        "account": {k: user.get(k) for k in
                    ("id", "email", "name", "role", "tier", "org_name",
                     "created_at")},
        "projects": [
            {k: p[k] for k in ("id", "name", "kind", "data", "created_at",
                               "updated_at") if k in p}
            | {"shared": bool(p.get("share_token"))}
            for p in db.list_projects(uid)
        ],
        "audit": db.list_audit_for_user(uid),
        # Model tunings are the user's own measurements turned into a
        # correction; they leave with them and come back in an export.
        "calibrations": [
            {k: c[k] for k in ("id", "name", "technology", "created_at",
                               "data") if k in c}
            for c in db.list_calibrations(uid) if c.get("user_id") == uid
        ],
        "files": {
            "dxf": [{"dxf_id": i, "filename": d.get("filename")}
                    for i, d in _owned_dxf(uid)],
            "antennas": [{"antenna_id": i, "name": d.get("name")}
                         for i, d in _owned_antennas(uid)],
            "results": [{"result": stem, "kind": m.get("kind"),
                         "created_at": m.get("created_at")}
                        for stem, m in _owned_results(uid)],
            "logo": bool(user.get("logo_path")),
        },
    }


def erase_account(user: dict) -> dict:
    """Delete the account and everything it owns; returns a receipt.

    The receipt is not decoration: a data-protection request has to be
    answerable with *what* was destroyed, and the caller (and the audit
    trail) gets counts rather than a bare 204.
    """
    uid = user["id"]
    receipt = {"projects": 0, "dxf": 0, "antennas": 0, "results": 0,
               "calibrations": 0, "logo": False, "audit_pseudonymised": 0}

    for dxf_id, _ in _owned_dxf(uid):
        from ..dxf.store import get_dxf_store
        if get_dxf_store().delete(dxf_id):
            receipt["dxf"] += 1

    for antenna_id, _ in _owned_antennas(uid):
        (ANTENNA_DIR / f"{antenna_id}.json").unlink(missing_ok=True)
        try:            # drop the in-process cache entry too
            from ..rf import antenna as _antenna
            with _antenna._lock:
                _antenna._mem.pop(antenna_id, None)
        except Exception:                              # pragma: no cover
            pass
        receipt["antennas"] += 1

    for stem, _ in _owned_results(uid):
        base = RESULTS_DIR / stem
        for suffix in (".json", ".png", ".npz"):
            base.with_suffix(suffix).unlink(missing_ok=True)
        # The raster also sits in this worker's hot cache, keyed by the same
        # "<kind>-<id>" stem; unlinking the file alone would keep serving it.
        from .. import results_store
        with results_store._lock:
            results_store._mem.pop(stem, None)
        receipt["results"] += 1

    logo = user.get("logo_path")
    if logo:
        try:
            Path(logo).unlink(missing_ok=True)
            receipt["logo"] = True
        except OSError:
            pass

    receipt["projects"] = db.count_projects(uid)
    receipt["calibrations"] = sum(1 for c in db.list_calibrations(uid)
                                  if c.get("user_id") == uid)
    receipt["audit_pseudonymised"] = len(db.list_audit_for_user(uid,
                                                                limit=50_000))
    # Last: the row itself. Tokens and projects cascade, audit rows are
    # re-attributed to an opaque subject (see db.delete_user).
    receipt["subject"] = db.delete_user(uid)
    return receipt
