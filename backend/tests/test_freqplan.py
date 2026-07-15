"""Tests: automatic frequency / PCI planning (C3)."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.rf.freqplan import (assign_channels, assign_pci,
                                      interference_matrix, plan_frequencies,
                                      sinr_stats)
from app.services.terrain.coverage import CoverageEngine
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


# ------------------------------------------------------------- unit: solver
def test_strongest_coupled_pair_gets_different_channels():
    # Site 0 and 1 couple hard; 2 is far away.
    I = np.array([[0.0, 1e-6, 1e-12],
                  [1e-6, 0.0, 1e-12],
                  [1e-12, 1e-12, 0.0]])
    chan = assign_channels(I, n_channels=2)
    assert chan[0] != chan[1]


def test_adjacent_channel_penalty_prefers_spaced_channels():
    # Three sites in a coupling chain with 3 channels available: the middle
    # site should avoid both co-channel AND adjacent-channel with neighbours
    # when a further channel exists.
    I = np.array([[0.0, 1e-6, 0.0],
                  [1e-6, 0.0, 1e-6],
                  [0.0, 1e-6, 0.0]])
    chan = assign_channels(I, n_channels=3, aci_db=10.0)  # strong ACI penalty
    assert chan[1] not in (chan[0], chan[2])


def test_pci_avoids_mod3_collision_between_coupled_sites():
    I = np.array([[0.0, 1e-6], [1e-6, 0.0]])
    pci = assign_pci(I, chan=[0, 0])
    assert pci[0] % 3 != pci[1] % 3


def test_sinr_improves_with_plan_synthetic():
    # Two totally overlapping equal-power cells: reuse-1 SINR ~ 0 dB; with two
    # channels the interferer disappears -> SINR jumps to S/N.
    f = np.full((2, 8, 8), -80.0)
    best = np.zeros((8, 8), dtype=int); best[4:, :] = 1
    covered = np.ones((8, 8), dtype=bool)
    base = sinr_stats(f, best, covered, None, noise_dbm=-104.0)
    planned = sinr_stats(f, best, covered, [0, 1], noise_dbm=-104.0)
    assert base["mean_sinr_db"] == pytest.approx(0.0, abs=0.1)   # I == S
    assert planned["mean_sinr_db"] > base["mean_sinr_db"] + 15.0


# --------------------------------------------------- integration: full plan
def test_plan_beats_reuse1_on_cluster(fake_store):
    from app.services.rf.technologies import get_technology
    engine = CoverageEngine(TerrainFusionService(store=fake_store))
    tech = get_technology("lte1800")
    computed = []
    for r in range(2):
        for c in range(3):
            polar = engine.compute_polar(47.0 + 0.03 * r, 15.0 + 0.03 * c,
                                         dict(tech), radius_m=4000.0,
                                         n_radials=48, n_steps=32)
            computed.append({"lat": 47.0 + 0.03 * r, "lon": 15.0 + 0.03 * c,
                             "name": None, "radius_m": 4000.0, "polar": polar})
    res = plan_frequencies(computed, n_channels=3, noise_dbm=-104.0, grid_n=96)
    assert res["gain_mean_sinr_db"] is not None
    # The roadmap success criterion: post-plan mean SINR > reuse-1 baseline.
    assert res["sinr_after_plan"]["mean_sinr_db"] \
        > res["sinr_reuse1_baseline"]["mean_sinr_db"] + 3.0
    assert len({a["channel"] for a in res["assignments"]}) > 1
    assert all(0 <= a["pci"] < 504 for a in res["assignments"])


# ------------------------------------------------------------- API layer
def test_frequency_plan_api(client):
    sites = [{"lat": 47.0 + 0.03 * r, "lon": 15.0 + 0.03 * c}
             for r in range(2) for c in range(3)]
    resp = client.post("/api/rf/frequency-plan", json={
        "sites": sites, "technology": "lte1800", "radius_km": 4,
        "n_channels": 3, "n_radials": 48, "n_steps": 32, "grid_n": 96})
    assert resp.status_code == 200, resp.text
    d = resp.json()
    assert d["sinr_after_plan"]["mean_sinr_db"] \
        > d["sinr_reuse1_baseline"]["mean_sinr_db"]
    assert len(d["assignments"]) == 6


def test_frequency_plan_needs_two_sites(client):
    resp = client.post("/api/rf/frequency-plan", json={
        "sites": [{"lat": 47.0, "lon": 15.0}], "technology": "lte1800"})
    assert resp.status_code == 422
