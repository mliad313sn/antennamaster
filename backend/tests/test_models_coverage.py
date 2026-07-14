"""Tests for propagation models, technology presets and the coverage engine."""
import numpy as np
import pytest

from app.services.rf.models import (MODEL_INFO, cost231_hata_db, deygout_loss_db,
                                    fspl_db, okumura_hata_db, path_loss_db,
                                    tr38901_rma_db, tr38901_uma_db, tr38901_umi_db)
from app.services.rf.physics import apply_earth_curvature
from app.services.rf.technologies import TECHNOLOGIES, get_technology, link_budget
from app.services.terrain.coverage import CoverageEngine
from app.services.terrain.fusion import TerrainFusionService


# ------------------------------------------------------------------- models
def test_fspl_reference_value():
    # 1 km @ 1000 MHz: 32.44 + 0 + 60 = 92.44 dB (textbook value)
    assert fspl_db(np.array([1000.0]), 1000.0)[0] == pytest.approx(92.44, abs=0.01)


def test_okumura_hata_urban_reference():
    # Hand-computed: f=900, hb=30, hm=1.5, d=5 km urban -> 151.0 dB
    L = okumura_hata_db(np.array([5000.0]), 900.0, 30.0, 1.5, "urban")[0]
    assert L == pytest.approx(151.0, abs=0.5)
    # Environment ordering: urban > suburban > open for identical geometry.
    Ls = okumura_hata_db(np.array([5000.0]), 900.0, 30.0, 1.5, "suburban")[0]
    Lo = okumura_hata_db(np.array([5000.0]), 900.0, 30.0, 1.5, "open")[0]
    assert L > Ls > Lo


def test_cost231_hata_above_hata():
    # At 1800 MHz COST-231 must exceed the 900 MHz Hata loss (higher f).
    L18 = cost231_hata_db(np.array([5000.0]), 1800.0, 30.0, 1.5, "urban")[0]
    L09 = okumura_hata_db(np.array([5000.0]), 900.0, 30.0, 1.5, "urban")[0]
    assert L18 > L09


def test_tr38901_families():
    d = np.array([200.0, 1000.0, 3000.0])
    for fn, f in ((tr38901_rma_db, 700.0), (tr38901_uma_db, 3500.0),
                  (tr38901_umi_db, 28000.0)):
        los = fn(d, f, 25.0, 1.5, "los")
        nlos = fn(d, f, 25.0, 1.5, "nlos")
        assert np.all(nlos >= los - 1e-9)          # NLOS never better than LOS
        assert np.all(np.diff(los) > 0)            # monotonic with distance
        # Never better than free space (guaranteed by dispatcher, check raw too)
        assert np.all(nlos + 5.0 > fspl_db(d, f))


def test_path_loss_dispatch_and_warnings():
    loss, warns = path_loss_db("okumura_hata", np.array([2000.0]), 3500.0, 30, 1.5)
    assert warns and "validity" in warns[0]        # 3.5 GHz outside Hata range
    with pytest.raises(ValueError):
        path_loss_db("nope", np.array([1.0]), 900, 30, 1.5)
    assert set(MODEL_INFO) == {"fspl", "okumura_hata", "cost231_hata",
                               "tr38901_rma", "tr38901_uma", "tr38901_umi"}


def test_deygout_multi_edge():
    d = np.linspace(0, 20_000, 201)
    flat = np.full_like(d, 100.0)
    curved = apply_earth_curvature(d, flat)
    # 20 km flat path with 30 m masts grazes the first Fresnel zone at 446
    # MHz -> a small (but nonzero) grazing loss is physically correct.
    assert deygout_loss_db(d, curved, 30, 30, 446) < 3.0
    # Two 150 m ridges -> loss must exceed the single-edge loss of one ridge.
    one = curved.copy(); one[60:64] += 150.0
    two = one.copy(); two[140:144] += 150.0
    l1 = deygout_loss_db(d, one, 30, 30, 446)
    l2 = deygout_loss_db(d, two, 30, 30, 446)
    assert l1 > 6.0
    assert l2 > l1 + 3.0


# ------------------------------------------------------------- technologies
def test_technology_presets_cover_all_generations():
    gens = {t["generation"] for t in TECHNOLOGIES.values()}
    assert {"2G", "3G", "4G", "5G", "PMR", "Broadcast", "WLAN", "IoT",
            "Backhaul", "Custom"} <= gens
    for key, t in TECHNOLOGIES.items():
        assert t["model"] in MODEL_INFO, f"{key} references unknown model"
        lo, hi = MODEL_INFO[t["model"]]["f_range_mhz"]
        assert lo <= t["freq_mhz"] <= hi, f"{key} default freq outside its model"


def test_link_budget_math():
    tech = get_technology("gsm900")
    b = link_budget(tech, path_loss_db_value=120.0, diffraction_db=10.0)
    expected = 43.0 + 15.0 + 0.0 - 3.0 - 120.0 - 10.0
    assert b["rx_power_dbm"] == pytest.approx(expected)
    assert b["served"] == (expected >= -102.0)


# ----------------------------------------------------------------- coverage
def test_coverage_engine_smoke(fake_store):
    engine = CoverageEngine(TerrainFusionService(store=fake_store))
    tech = get_technology("gsm900")
    res = engine.simulate(47.0, 15.0, tech, radius_m=5000.0,
                          n_radials=36, n_steps=40, raster_px=128)
    assert res.png[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(res.legend) == 5
    assert 0.0 <= res.stats["served_area_fraction"] <= 1.0
    # GSM900 macro site over gentle terrain should serve most of a 5 km disc.
    assert res.stats["served_area_fraction"] > 0.5
    (s, w), (n, e) = res.bounds
    assert s < 47.0 < n and w < 15.0 < e


def test_coverage_sector_antenna(fake_store):
    engine = CoverageEngine(TerrainFusionService(store=fake_store))
    tech = get_technology("gsm900")
    omni = engine.simulate(47.0, 15.0, tech, radius_m=8000.0,
                           n_radials=36, n_steps=30, raster_px=64)
    sect = engine.simulate(47.0, 15.0, tech, radius_m=8000.0,
                           n_radials=36, n_steps=30, raster_px=64,
                           antenna_azimuth_deg=90.0, antenna_beamwidth_deg=65.0)
    # A sector serves less area than an omni with identical power.
    assert sect.stats["served_area_fraction"] < omni.stats["served_area_fraction"]
