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

import math

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
    "lte_cpe": ("LTE/5G CPE / cellular router", "lte1800", "cost231_hata"),
    "wisp_antenna": ("Fixed-wireless (WISP) antenna", "wifi5800", "fspl"),
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
    "lte_cpe": (23.0, -95.0), "wisp_antenna": (23.0, -82.0),
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



# A high-gain antenna is directional by construction: an omni cannot focus
# 27 dBi. When a record carries no measured beamwidth we derive one from the
# gain rather than defaulting to 360 deg, which used to paint a point-to-point
# dish as a full-circle donut claiming coverage over a whole township.
#
# G(dBi) = 10 log10(29000 / (theta_h * theta_v)); for a symmetric aperture
# that inverts to theta = sqrt(29000 / 10^(G/10)). 27 dBi -> 7.6 deg,
# 24.5 -> 10.1, 16 -> 27 - all within a degree or two of the real datasheets.
_OMNI_GAIN_CEILING_DBI = 15.0


def beamwidth_for(spatial: dict, gain_dbi: float | None) -> tuple[float, str]:
    """(beamwidth_deg, source) - never silently claims omni for a dish."""
    measured = (spatial or {}).get("h_beamwidth_deg")
    if measured:
        return float(measured), "datasheet"
    if gain_dbi is not None and float(gain_dbi) > _OMNI_GAIN_CEILING_DBI:
        theta = math.sqrt(29000.0 / (10.0 ** (float(gain_dbi) / 10.0)))
        return round(max(theta, 3.0), 1), "inferred_from_gain"
    return 360.0, "assumed_omni"


def confidence_for(declared: str, has_sens: bool, bw_source: str) -> str:
    """Never claim 'datasheet' for a spec this catalog invented.

    Two things count as invented: a sensitivity inherited from the class
    default (how -70 dBm ended up on LTU radios whose real figure is near
    -96), and a beamwidth derived from gain. An omni assumed for a low-gain
    device is NOT invented - it is the physically-sound default for that
    class, and downgrading it would just make the label meaningless.
    """
    if declared == "datasheet" and (not has_sens
                                    or bw_source == "inferred_from_gain"):
        return "inferred"
    return declared


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
    beamwidth, bw_source = beamwidth_for(spatial, gain)
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
        "sensitivity_source": ("datasheet" if rf.get("rx_sensitivity_dbm")
                               is not None else "class_default"),
        "antenna_gain_dbi": float(gain if gain is not None else 0.0),
        "beamwidth_deg": beamwidth,
        "beamwidth_source": bw_source,
        # Rich fields preserved for advanced callers / the physics engine.
        "frequency_bands_mhz": bands,
        "rf_specs": rf,
        "spatial_characteristics": spatial,
        "environment_rating": rec.get("environment_rating", {}),
        "region_of_origin": rec.get("region_of_origin", "Unknown"),
        "provenance": rec.get("provenance", "unspecified"),
        # A record is only "datasheet" if the fields the study actually uses
        # came from one. Inheriting a class-default sensitivity or inferring a
        # beamwidth and still claiming "datasheet" is how -70 dBm ended up on
        # LTU radios whose real sensitivity is near -96.
        "spec_confidence": confidence_for(
            rec.get("spec_confidence", "class_reference"),
            rf.get("rx_sensitivity_dbm") is not None,
            bw_source),
    }
    if rec.get("leaky_feeder_specs"):
        out["leaky_feeder_specs"] = rec["leaky_feeder_specs"]
    if rec.get("also_sold_as"):
        out["also_sold_as"] = list(rec["also_sold_as"])
    if rec.get("oem_reference"):
        out["oem_reference"] = rec["oem_reference"]
    if rec.get("variant_group"):
        out["variant_group"] = rec["variant_group"]
    for extra in ("source_url", "datasheet_url"):
        if rec.get(extra):
            out[extra] = rec[extra]
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
    genuinely different products share a 65°/18 dBi or a 64T64R/53 dBm envelope,
    and at catalog scale even datasheet-precise reduced fingerprints collide
    (two different Wi-Fi APs can both be "30 dBm / 6 dBi / 5+6 GHz").  So a
    merge requires EXPLICIT evidence of shared hardware:

      * an ``oem_reference`` (a shared ODM / reference-design id) — the true
        signature of a rebrand, even across manufacturers; OR
      * the SAME manufacturer with a shared ``variant_group`` declaration (a
        jacket/packaging variant of one RF core, e.g. the fire-retardant
        version of a radiating cable) — stated in the source record, never
        inferred from spec coincidence.

    Everything else stays distinct (returns a unique object identity).
    """
    oem = e.get("oem_reference")
    if oem:
        return ("oem", oem)
    vg = e.get("variant_group")
    if vg:
        return ("variant", e.get("vendor"), vg)
    return ("unique", id(e))     # never auto-merge on spec coincidence


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
