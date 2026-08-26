"""Hardware Catalog — a structured, extensible database of real equipment
profiles (Wi-Fi, Private LTE, PTP microwave, PMR).

Each profile carries the planning attributes an operator selects by name
instead of by RF number: frequency band, TX power, RX sensitivity, antenna
gain and beamwidth — plus the base technology/propagation model the physics
engine should use.  The bundled catalog lives in ``app/data/hardware_catalog
.json``; sites may extend or override it by dropping a ``hardware_catalog
.json`` into ``AM_DATA_DIR`` (merged by ``id``), so field teams can add their
own gear without code changes.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from ...config import DATA_DIR

_BUNDLED = Path(__file__).resolve().parent.parent.parent / "data" / "hardware_catalog.json"

# The fields every profile must expose to the Equipment Selector.
REQUIRED = ("id", "vendor", "model", "category", "band_label", "freq_mhz",
            "tx_power_dbm", "rx_sensitivity_dbm", "antenna_gain_dbi",
            "beamwidth_deg")


def _load_file(path: Path) -> list[dict]:
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    items = raw.get("equipment", raw) if isinstance(raw, dict) else raw
    return [e for e in items if isinstance(e, dict) and "id" in e]


@lru_cache(maxsize=1)
def _catalog() -> dict[str, dict]:
    by_id: dict[str, dict] = {}
    for e in _load_file(_BUNDLED):
        by_id[e["id"]] = e
    # Operator overrides / additions from the data volume win by id.
    override = DATA_DIR / "hardware_catalog.json"
    if override.exists() and override.resolve() != _BUNDLED.resolve():
        for e in _load_file(override):
            by_id[e["id"]] = {**by_id.get(e["id"], {}), **e}
    # Keep only well-formed entries, and never serve a fabricated spec.
    return {k: _sanitize(v) for k, v in by_id.items()
            if all(f in v for f in REQUIRED)}


def _sanitize(entry: dict) -> dict:
    """Repair specs the catalog cannot honestly claim.

    A catalog entry may reach us with beamwidth 360 while carrying 27 dBi of
    gain - which no omni can do. Selecting it painted a point-to-point dish as
    a full-circle donut, claiming coverage over a whole township, and the
    entry still advertised spec_confidence "datasheet". Applied here rather
    than only in the ingest script so an operator's own catalog dropped into
    AM_DATA_DIR gets the same guarantee.
    """
    from .catalog_ingest import beamwidth_for, confidence_for

    e = dict(entry)
    gain = e.get("antenna_gain_dbi")
    declared_bw = e.get("beamwidth_deg")
    # Treat a 360 on a high-gain entry as "unstated", not as a measurement.
    spatial = e.get("spatial_characteristics") or {}
    stated = spatial.get("h_beamwidth_deg")
    if not stated and declared_bw and float(declared_bw) < 360.0:
        stated = declared_bw                      # a real per-entry beamwidth
    bw, bw_source = beamwidth_for({"h_beamwidth_deg": stated}, gain)
    e["beamwidth_deg"] = bw
    e.setdefault("beamwidth_source", bw_source)

    has_sens = bool((e.get("rf_specs") or {}).get("rx_sensitivity_dbm")) or \
        e.get("sensitivity_source") == "datasheet"
    e.setdefault("sensitivity_source",
                 "datasheet" if has_sens else "class_default")
    e["spec_confidence"] = confidence_for(
        e.get("spec_confidence", "class_reference"),
        e["sensitivity_source"] == "datasheet", bw_source)
    return e


def list_equipment() -> list[dict]:
    """All catalog entries, grouped-friendly (sorted by category then model)."""
    items = list(_catalog().values())
    items.sort(key=lambda e: (e.get("category", ""), e.get("model", "")))
    return items


def get_equipment(equipment_id: str) -> dict | None:
    return _catalog().get(equipment_id)


def categories() -> list[str]:
    seen: list[str] = []
    for e in list_equipment():
        c = e.get("category", "Other")
        if c not in seen:
            seen.append(c)
    return seen
