"""Hardware-catalog ingestion pipeline: normalize → deduplicate → emit.

Turns *source records* — device entries in the rich, extensible schema
(``equipment_class``, ``frequency_bands_mhz``, nested ``rf_specs``,
``leaky_feeder_specs`` …) — into the flat profiles the Equipment Selector and
the physics engine consume, while preserving the full detail for callers that
want it.

Three stages, each independently testable:

  1. NORMALIZE — derive the flat planning fields the selector requires
     (``freq_mhz``, ``antenna_gain_dbi``, ``beamwidth_deg`` …) from the nested
     structure, and attach a class → technology / propagation-model default so
     any device is immediately usable in a study.
  2. DEDUPLICATE — merge re-branded OEM hardware: records whose *normalized RF
     fingerprint* (class + band + gain + power + key specs) matches are the same
     physical device sold under different names; they collapse into one
     canonical entry whose ``also_sold_as`` lists the rebrands.
  3. EMIT — write the merged catalog (``equipment`` list + ``_meta``) that
     ``hardware.py`` loads.

Every record carries its own ``provenance`` and ``spec_confidence`` so the
catalog is honest about where each number came from (a datasheet, a vendor's
published typical, or a class-reference engineering value) — the physics engine
never silently trusts an unverified number as if it were a guarantee.

The public entry point ``ingest_sources`` is async so real datasheet fetchers
(HTTP, PDF) can be plugged into ``load_source`` without changing the pipeline;
the bundled sources are local JSON.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

# equipment_class → (human category, default technology preset, default model).
CLASS_DEFAULTS: dict[str, tuple[str, str, str]] = {
    "macro_antenna": ("Macro cellular antenna", "lte1800", "cost231_hata"),
    "massive_mimo": ("Massive-MIMO active radio", "nr3500", "tr38901_uma"),
    "small_cell": ("Small cell / street radio", "nr3500", "tr38901_umi"),
    "microwave_ptp": ("PtP / PtMP microwave", "ptp18000", "fspl"),
    "mmwave_ptp": ("mmWave backhaul (E/V-band)", "ptp18000", "fspl"),
    "leaky_feeder": ("Leaky feeder / radiating cable", "custom", "fspl"),
    "tunnel_antenna": ("Tunnel / confined-space antenna", "pmr446", "okumura_hata"),
    "lmr_repeater": ("LMR / PMR repeater", "tetra400", "okumura_hata"),
    "lmr_antenna": ("LMR base / vehicular antenna", "vhf150", "okumura_hata"),
    "wifi_ap": ("Enterprise Wi-Fi AP", "wifi5800", "tr38901_umi"),
    "iot_gateway": ("IoT / LoRaWAN gateway", "lora868", "okumura_hata"),
    "iot_module": ("Embedded IoT / RedCap module", "lora868", "okumura_hata"),
    "gnss": ("GNSS / GPS tracker", "custom", "fspl"),
}

# Flat fields the Equipment Selector + hardware.py require.
REQUIRED = ("id", "vendor", "model", "category", "band_label", "freq_mhz",
            "tx_power_dbm", "rx_sensitivity_dbm", "antenna_gain_dbi",
            "beamwidth_deg")

# Class-reference receiver sensitivity / power fallbacks (engineering-standard
# planning values, used only when a record does not carry its own).
_CLASS_FALLBACK = {
    "lmr_repeater": (44.0, -119.0), "lmr_antenna": (44.0, -119.0),
    "macro_antenna": (46.0, -105.0), "massive_mimo": (49.0, -100.0),
    "small_cell": (37.0, -100.0), "microwave_ptp": (20.0, -70.0),
    "mmwave_ptp": (10.0, -60.0), "leaky_feeder": (20.0, -95.0),
    "tunnel_antenna": (30.0, -100.0), "wifi_ap": (23.0, -82.0),
    "iot_gateway": (16.0, -137.0), "iot_module": (14.0, -110.0),
    "gnss": (0.0, -160.0),
}


def _band_midpoint(bands: list) -> float:
    lo, hi = bands[0][0], bands[0][1]
    return round((float(lo) + float(hi)) / 2.0, 1)


def _band_label(bands: list) -> str:
    parts = []
    for lo, hi in bands:
        if hi >= 1000:
            parts.append(f"{lo/1000:g}–{hi/1000:g} GHz" if lo >= 1000
                         else f"{lo:g} MHz–{hi/1000:g} GHz")
        else:
            parts.append(f"{lo:g}–{hi:g} MHz")
    return ", ".join(parts)


def normalize(rec: dict) -> dict | None:
    """Rich source record → a flat, selector-ready profile (nested kept too)."""
    cls = rec.get("equipment_class")
    if cls not in CLASS_DEFAULTS or "id" not in rec:
        return None
    category, tech, model = CLASS_DEFAULTS[cls]
    bands = rec.get("frequency_bands_mhz") or [[float(rec.get("freq_mhz", 1))] * 2]
    rf = rec.get("rf_specs", {}) or {}
    spatial = rec.get("spatial_characteristics", {}) or {}
    p_pow, p_sens = _CLASS_FALLBACK.get(cls, (30.0, -100.0))

    gain = rf.get("gain_dbi")
    out = {
        "id": rec["id"],
        "vendor": rec.get("manufacturer", "Unknown"),
        "model": rec.get("model", rec["id"]),
        "category": category,
        "equipment_class": cls,
        "band_label": _band_label(bands),
        "technology": rec.get("technology", tech),
        "model_key": rec.get("model_key", model),
        "environment": rec.get("environment", "urban"),
        "freq_mhz": _band_midpoint(bands),
        "tx_power_dbm": float(rf.get("max_tx_power_dbm", p_pow)),
        "rx_sensitivity_dbm": float(rf.get("rx_sensitivity_dbm", p_sens)),
        "antenna_gain_dbi": float(gain if gain is not None else 0.0),
        "beamwidth_deg": float(spatial.get("h_beamwidth_deg") or 360.0),
        # Rich fields preserved for advanced callers / the physics engine.
        "frequency_bands_mhz": bands,
        "rf_specs": rf,
        "spatial_characteristics": spatial,
        "environment_rating": rec.get("environment_rating", {}),
        "region_of_origin": rec.get("region_of_origin", "Unknown"),
        "provenance": rec.get("provenance", "unspecified"),
        "spec_confidence": rec.get("spec_confidence", "class_reference"),
    }
    if rec.get("leaky_feeder_specs"):
        out["leaky_feeder_specs"] = rec["leaky_feeder_specs"]
    if rec.get("also_sold_as"):
        out["also_sold_as"] = list(rec["also_sold_as"])
    if rec.get("oem_reference"):
        out["oem_reference"] = rec["oem_reference"]
    return out


def _fingerprint(e: dict) -> tuple:
    """RF identity of a device, brand-agnostic — the dedup key for OEM rebrands.

    Two records with the same class, band envelope, gain, power and (for cables)
    coupling/attenuation are the same physical hardware under different labels.
    """
    bands = tuple(tuple(round(float(x)) for x in b)
                  for b in e.get("frequency_bands_mhz", []))
    lf = e.get("leaky_feeder_specs", {})
    lf_sig = tuple(sorted((round(float(p.get("freq_mhz", 0))),
                           round(float(p.get("atten_db_per_100m", 0)), 1))
                          for p in lf.get("points", [])))
    return (
        e.get("equipment_class"), bands,
        round(float(e.get("antenna_gain_dbi", 0)), 1),
        round(float(e.get("tx_power_dbm", 0)), 1),
        round(float(e.get("rx_sensitivity_dbm", 0)), 1),
        round(float(e.get("beamwidth_deg", 0))), lf_sig,
    )


# Confidence ranking so the best-sourced record becomes canonical on a merge.
_CONF_RANK = {"datasheet": 3, "published_typical": 2, "class_reference": 1}


def _dedup_key(e: dict):
    """The identity two records must share to be treated as the SAME physical
    device sold under different labels.

    Coincident *planning ballparks* are NOT evidence of a rebrand — many
    genuinely different products share a 65°/18 dBi or a 64T64R/53 dBm envelope.
    So a merge requires real evidence of shared hardware:

      * an explicit ``oem_reference`` (a shared ODM / reference-design id) — the
        true signature of a rebrand, even across manufacturers; OR
      * the SAME manufacturer with datasheet-precise, identical specs (a jacket/
        variant of one RF core, e.g. a fire-retardant version of a cable).

    Everything else stays distinct (returns a unique object identity).
    """
    oem = e.get("oem_reference")
    if oem:
        return ("oem", oem)
    if e.get("spec_confidence") == "datasheet":
        return ("vendor_fp", e.get("vendor"), _fingerprint(e))
    return ("unique", id(e))     # never auto-merge coarse/estimated specs


def deduplicate(entries: list[dict]) -> tuple[list[dict], int]:
    """Merge OEM-rebranded / variant duplicates. Returns (unique, n_merged)."""
    groups: dict = {}
    for e in entries:
        groups.setdefault(_dedup_key(e), []).append(e)

    merged: list[dict] = []
    n_merged = 0
    for group in groups.values():
        if len(group) == 1:
            merged.append(group[0]); continue
        group.sort(key=lambda e: (_CONF_RANK.get(e.get("spec_confidence"), 0),
                                  len(e)), reverse=True)
        canon = dict(group[0])
        aliases = set(canon.get("also_sold_as", []))
        for other in group[1:]:
            aliases.add(f"{other.get('vendor', '?')} {other.get('model', '')}".strip())
            aliases.update(other.get("also_sold_as", []))
            n_merged += 1
        if aliases:
            canon["also_sold_as"] = sorted(aliases)
        merged.append(canon)
    return merged, n_merged


async def load_source(path_or_url: str) -> list[dict]:
    """Load one source of raw device records.

    Local JSON today; the async signature lets a real datasheet fetcher (HTTP
    catalog, FCC-ID export, PDF table extractor) be dropped in unchanged.
    """
    def _read() -> list[dict]:
        raw = json.loads(Path(path_or_url).read_text())
        return raw.get("devices", raw) if isinstance(raw, dict) else raw
    return await asyncio.to_thread(_read)


async def ingest_sources(paths: list[str]) -> dict:
    """Full pipeline over many sources, concurrently: load → normalize → dedup."""
    batches = await asyncio.gather(*(load_source(p) for p in paths))
    raw = [r for batch in batches for r in batch]
    normalized = [n for n in (normalize(r) for r in raw) if n]
    unique, n_merged = deduplicate(normalized)
    unique.sort(key=lambda e: (e.get("equipment_class", ""), e.get("model", "")))
    return {
        "equipment": unique,
        "stats": {"raw": len(raw), "normalized": len(normalized),
                  "unique": len(unique), "merged_rebrands": n_merged},
    }
