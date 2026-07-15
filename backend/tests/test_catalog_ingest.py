"""Tests: hardware-catalog ingestion (normalize / dedup) and the guarantee that
the RF physics engine processes the entire expanded inventory without exceptions."""
import asyncio

import numpy as np
import pytest

import app.services.rf.hardware as hardware
from app.services.rf.catalog_ingest import (deduplicate, ingest_sources,
                                            normalize)
from app.services.rf.leakyfeeder import leaky_feeder_profile
from app.services.rf.technologies import (effective_sensitivity_dbm,
                                          link_budget)


# ------------------------------------------------------------- normalization
def test_normalize_derives_flat_fields_from_rich_schema():
    rec = {
        "id": "acme-x1", "manufacturer": "Acme", "model": "X1 65° panel",
        "equipment_class": "macro_antenna", "region_of_origin": "Europe",
        "frequency_bands_mhz": [[1710, 2170]],
        "rf_specs": {"gain_dbi": 18.0, "max_tx_power_dbm": 46},
        "spatial_characteristics": {"h_beamwidth_deg": 65},
        "provenance": "datasheet", "spec_confidence": "datasheet",
    }
    n = normalize(rec)
    assert n["freq_mhz"] == pytest.approx(1940.0)          # band midpoint
    assert n["antenna_gain_dbi"] == 18.0
    assert n["beamwidth_deg"] == 65.0
    assert n["category"] == "Macro cellular antenna"       # class → label
    assert n["technology"] and n["model_key"]              # study defaults filled
    assert all(f in n for f in hardware.REQUIRED)


def test_normalize_rejects_unknown_class():
    assert normalize({"id": "x", "equipment_class": "flux_capacitor"}) is None


# --------------------------------------------------------------- dedup logic
def _mk(id, vendor, cls="massive_mimo", gain=24, power=53, conf="class_reference",
        band=(3400, 3600), oem=None, sens=-100):
    e = {"id": id, "vendor": vendor, "model": id, "equipment_class": cls,
         "antenna_gain_dbi": gain, "tx_power_dbm": power, "rx_sensitivity_dbm": sens,
         "beamwidth_deg": 105, "frequency_bands_mhz": [list(band)],
         "spec_confidence": conf}
    if oem:
        e["oem_reference"] = oem
    return e


def test_dedup_merges_explicit_oem_rebrands():
    a = _mk("rak", "RAK", cls="iot_gateway", gain=2, power=27, sens=-139,
            conf="published_typical", band=(863, 870), oem="sx1302-eu868")
    b = _mk("seeed", "Seeed", cls="iot_gateway", gain=2, power=27, sens=-139,
            conf="published_typical", band=(863, 870), oem="sx1302-eu868")
    merged, n = deduplicate([a, b])
    assert len(merged) == 1 and n == 1
    assert merged[0].get("also_sold_as")


def test_dedup_does_not_merge_distinct_products_with_coincident_specs():
    # Huawei and ZTE happen to share a 64T64R / 53 dBm / 24 dBi envelope — they
    # are NOT the same hardware, so coarse class_reference specs must NOT merge.
    hua = _mk("huawei-aau", "Huawei")
    zte = _mk("zte-a9611", "ZTE")
    merged, n = deduplicate([hua, zte])
    assert len(merged) == 2 and n == 0


def test_dedup_merges_same_vendor_datasheet_variants():
    # Same vendor, datasheet-precise, identical fingerprint = a jacket variant.
    rlkw = _mk("rlkw", "RFS", cls="leaky_feeder", gain=0, power=20, sens=-95,
               conf="datasheet", band=(75, 1000))
    rlku = _mk("rlku", "RFS", cls="leaky_feeder", gain=0, power=20, sens=-95,
               conf="datasheet", band=(75, 1000))
    merged, n = deduplicate([rlkw, rlku])
    assert len(merged) == 1 and n == 1
    # But a DIFFERENT vendor with the same datasheet specs stays separate.
    other = _mk("cs", "CommScope", cls="leaky_feeder", gain=0, power=20,
                sens=-95, conf="datasheet", band=(75, 1000))
    merged2, n2 = deduplicate([rlkw, other])
    assert len(merged2) == 2 and n2 == 0


# ----------------------------------------------------- pipeline over sources
def test_ingest_sources_pipeline(tmp_path):
    import json
    src = tmp_path / "s.json"
    src.write_text(json.dumps({"devices": [
        {"id": "a", "manufacturer": "A", "model": "A", "equipment_class": "wifi_ap",
         "frequency_bands_mhz": [[5150, 5875]], "rf_specs": {"gain_dbi": 6},
         "spec_confidence": "class_reference"},
        {"id": "b", "manufacturer": "B", "model": "B", "equipment_class": "wifi_ap",
         "frequency_bands_mhz": [[5150, 5875]], "rf_specs": {"gain_dbi": 6},
         "oem_reference": "same-odm", "spec_confidence": "published_typical"},
        {"id": "c", "manufacturer": "C", "model": "C", "equipment_class": "wifi_ap",
         "frequency_bands_mhz": [[5150, 5875]], "rf_specs": {"gain_dbi": 6},
         "oem_reference": "same-odm", "spec_confidence": "published_typical"},
    ]}))
    out = asyncio.run(ingest_sources([str(src)]))
    assert out["stats"]["raw"] == 3
    assert out["stats"]["merged_rebrands"] == 1     # b+c share an ODM ref
    assert out["stats"]["unique"] == 2


# --------------------------------- the real physics engine over EVERY entry
def _tech_from_entry(e: dict) -> dict:
    return {
        "freq_mhz": float(e["freq_mhz"]),
        "tx_power_dbm": float(e["tx_power_dbm"]),
        "tx_gain_dbi": float(e["antenna_gain_dbi"]),
        "rx_gain_dbi": 0.0, "losses_db": 0.0,
        "rx_sensitivity_dbm": float(e["rx_sensitivity_dbm"]),
    }


def test_link_budget_processes_full_catalog():
    hardware._catalog.cache_clear()
    catalog = hardware.list_equipment()
    assert len(catalog) >= 40                       # the expanded inventory
    for e in catalog:
        tech = _tech_from_entry(e)
        # A realistic path loss must yield finite, ordered budget numbers for
        # every device — from a 0 dBm GNSS receiver to a 53 dBm massive-MIMO AAU.
        res = link_budget(tech, path_loss_db_value=120.0)
        assert np.isfinite(res["rx_power_dbm"])
        assert np.isfinite(res["margin_db"])
        assert isinstance(res["served"], bool)
        assert np.isfinite(effective_sensitivity_dbm(tech))


def test_leaky_feeder_engine_processes_every_cable():
    hardware._catalog.cache_clear()
    cables = [e for e in hardware.list_equipment()
              if e.get("equipment_class") == "leaky_feeder"]
    assert cables, "catalog must contain radiating cables"
    for c in cables:
        lf = c["leaky_feeder_specs"]
        for pt in lf["points"]:
            prof = leaky_feeder_profile(
                float(pt["freq_mhz"]), length_m=500.0,
                cable_atten_db_per_100m=float(pt["atten_db_per_100m"]),
                coupling_ref_db=float(pt["coupling_db_50"]),
                coupling_ref_m=float(lf.get("coupling_ref_m", 2.0)),
                tx_power_dbm=20.0, rx_sensitivity_dbm=-95.0)
            assert np.isfinite(prof["end_field_dbm"])
            assert 0.0 <= prof["served_length_fraction"] <= 1.0


def test_full_profile_engine_on_catalog_sample(fake_store):
    """Drive the complete fused-terrain link engine with catalog devices."""
    from app.services.rf.planning import evaluate_receiver
    from app.services.terrain.fusion import TerrainFusionService
    fusion = TerrainFusionService(store=fake_store)
    hardware._catalog.cache_clear()
    # One device per equipment_class through the real profile/diffraction engine.
    seen = set()
    for e in hardware.list_equipment():
        cls = e.get("equipment_class", "legacy")
        if cls in seen:
            continue
        seen.add(cls)
        tech = _tech_from_entry(e)
        tech.update(model="fspl", environment="open", h_bs_m=30.0, h_ut_m=1.5)
        res = evaluate_receiver(fusion, tech, 47.0, 15.0, 47.0, 15.05)
        assert np.isfinite(res["rx_power_dbm"]) and "served" in res
    assert len(seen) >= 8
