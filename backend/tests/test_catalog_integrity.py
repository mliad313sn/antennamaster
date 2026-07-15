"""Tests: catalog integrity CI (C7) — zero-hallucination invariant + scale.

The strategic roadmap's C7 target is a 500+ device catalog with ZERO invented
specs. Those two goals are ordered: the zero-hallucination invariant is
enforced HERE, in CI, forever; the count grows only through real datasheet
ingestion (the pipeline's scalability is proven below on clearly-labelled
synthetic records that are never shipped).
"""
import asyncio
import json

import pytest

import app.services.rf.hardware as hardware
from app.services.rf.catalog_ingest import ingest_sources

VALID_CONFIDENCE = {"datasheet", "published_typical", "class_reference"}


def _catalog():
    hardware._catalog.cache_clear()
    return hardware.list_equipment()


# --------------------------------------------- the zero-hallucination gate
def test_every_ingested_entry_declares_provenance_and_confidence():
    """No record may present a spec without saying where it came from."""
    for e in _catalog():
        if "equipment_class" not in e:
            continue                      # legacy generic profiles, pre-schema
        assert e.get("provenance"), f"{e['id']} has no provenance"
        assert e.get("spec_confidence") in VALID_CONFIDENCE, \
            f"{e['id']} has invalid spec_confidence {e.get('spec_confidence')!r}"


def test_every_entry_is_physically_sane():
    """Hallucinated numbers tend to violate physics bounds; none may ship."""
    for e in _catalog():
        assert 0 < e["freq_mhz"] < 300_000, e["id"]
        assert -30 <= e["tx_power_dbm"] <= 90, e["id"]
        assert -10 <= e["antenna_gain_dbi"] <= 60, e["id"]
        assert e["rx_sensitivity_dbm"] <= 0, e["id"]
        assert 0 < e["beamwidth_deg"] <= 360, e["id"]
        for lo, hi in e.get("frequency_bands_mhz", []):
            assert 0 < lo <= hi, e["id"]
        for pt in e.get("leaky_feeder_specs", {}).get("points", []):
            assert pt["atten_db_per_100m"] > 0, e["id"]
            assert 20 <= pt["coupling_db_50"] <= 110, e["id"]


def test_datasheet_claims_are_traceable():
    """spec_confidence=datasheet requires the provenance to actually cite a
    datasheet source, not a vague description."""
    for e in _catalog():
        if e.get("spec_confidence") == "datasheet":
            assert any(w in e["provenance"].lower()
                       for w in ("datasheet", "product data", "data sheet")), \
                f"{e['id']} claims datasheet confidence without citing one"


def test_confidence_accounting_matches_audit():
    """_meta counters must reflect reality (the audit doc is generated from
    them, so they must never drift)."""
    from pathlib import Path
    raw = json.loads((Path(hardware._BUNDLED)).read_text())
    counts = raw["_meta"]["counts"]["by_confidence"]
    actual: dict = {}
    for e in raw["equipment"]:
        key = e.get("spec_confidence", "legacy")
        actual[key] = actual.get(key, 0) + 1
    assert counts == dict(sorted(actual.items()))


# ------------------------------------------------------- pipeline at scale
def test_pipeline_handles_600_records(tmp_path):
    """Scale proof: 600 SYNTHETIC records (labelled as such, never shipped)
    flow through normalize→dedup correctly — the pipeline is ready for the
    real 500+ datasheet campaign."""
    devices = []
    for i in range(600):
        devices.append({
            "id": f"synthetic-{i}", "manufacturer": f"Vendor{i % 40}",
            "model": f"SYNTH-{i}", "equipment_class": "wifi_ap",
            "frequency_bands_mhz": [[5150 + (i % 5), 5875]],
            "rf_specs": {"gain_dbi": 3 + (i % 9),
                         "max_tx_power_dbm": 20 + (i % 6)},
            "provenance": "synthetic scale-test record (never shipped)",
            "spec_confidence": "class_reference",
            # every 3rd pair shares an ODM reference -> must merge
            **({"oem_reference": f"odm-{i // 2}"} if i % 3 != 2 else {}),
        })
    src = tmp_path / "scale.json"
    src.write_text(json.dumps({"devices": devices}))
    out = asyncio.run(ingest_sources([str(src)]))
    assert out["stats"]["raw"] == 600
    assert out["stats"]["normalized"] == 600
    assert out["stats"]["merged_rebrands"] > 0
    assert out["stats"]["unique"] < 600
    # Every surviving record kept its provenance & confidence.
    for e in out["equipment"]:
        assert e["provenance"] and e["spec_confidence"] in VALID_CONFIDENCE
