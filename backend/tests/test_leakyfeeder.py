"""Tests: leaky-feeder (radiating cable) & distributed-antenna tunnel design."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.rf.leakyfeeder import (coupling_loss_at,
                                         distributed_antenna_tunnel,
                                         leaky_feeder_amp_spacing_m,
                                         leaky_feeder_profile,
                                         tunnel_bend_loss_db)

client = TestClient(app)


# --------------------------------------------------------- unit: coupling loss
def test_coupling_loss_distance_scaling():
    # At the reference distance, the quoted figure holds; farther out it grows
    # 20 dB/decade; inside it does NOT drop below the quoted figure.
    assert coupling_loss_at(65.0, 2.0) == pytest.approx(65.0)
    assert coupling_loss_at(65.0, 20.0) == pytest.approx(85.0, abs=0.1)
    assert coupling_loss_at(65.0, 1.0) == pytest.approx(65.0)


def test_amp_spacing_restores_span_loss():
    # 3 dB/100m cable, 30 dB amp -> one amp covers 1000 m of run.
    assert leaky_feeder_amp_spacing_m(3.0, 30.0) == pytest.approx(1000.0)
    assert leaky_feeder_amp_spacing_m(0.0, 30.0) == float("inf")


def test_bend_loss_monotonic():
    # Tighter radius and higher frequency both raise the excess loss.
    gentle = tunnel_bend_loss_db(450.0, 5.0, radius_m=100.0)
    tight = tunnel_bend_loss_db(450.0, 5.0, radius_m=10.0)
    hi_freq = tunnel_bend_loss_db(900.0, 5.0, radius_m=10.0)
    assert tight > gentle
    assert hi_freq >= tight
    assert 1.0 <= gentle <= 40.0


# ----------------------------------------------------------- unit: feeder run
def test_leaky_feeder_amplifiers_extend_range():
    # A long, lossy run without amps drops below threshold; adding inline
    # amplifiers must extend the served length.
    common = dict(freq_mhz=450.0, length_m=3000.0,
                  cable_atten_db_per_100m=5.0, coupling_ref_db=65.0,
                  tx_power_dbm=20.0, rx_sensitivity_dbm=-95.0,
                  system_margin_db=10.0)
    passive = leaky_feeder_profile(**common)
    amplified = leaky_feeder_profile(**common, amp_gain_db=30.0)
    assert amplified["reliable_range_m"] > passive["reliable_range_m"]
    assert amplified["amp_spacing_m"] is not None
    assert amplified["amps_required"] >= 1
    # Field must decrease along a passive run (monotone loss).
    fields = [p["field_dbm"] for p in passive["points"]]
    assert fields[0] > fields[-1]


def test_leaky_feeder_bend_creates_gap_or_loss():
    base = leaky_feeder_profile(450.0, 1500.0, 4.0, tx_power_dbm=20.0,
                                rx_sensitivity_dbm=-95.0, system_margin_db=10.0)
    bent = leaky_feeder_profile(450.0, 1500.0, 4.0, tx_power_dbm=20.0,
                                rx_sensitivity_dbm=-95.0, system_margin_db=10.0,
                                bends=[{"position_m": 700.0, "radius_m": 8.0,
                                        "angle_deg": 90.0, "width_m": 5.0}])
    assert bent["end_field_dbm"] < base["end_field_dbm"]


# ---------------------------------------------------------- unit: DAS spacing
def test_distributed_antenna_uhf_beats_vhf_reach():
    # Same tunnel: UHF reaches farther than VHF (the lam^2/a^3 waveguide law),
    # so it needs fewer antennas.
    uhf = distributed_antenna_tunnel(900.0, 5.0, 4.0, 3000.0, eps_r=6.0)
    vhf = distributed_antenna_tunnel(150.0, 5.0, 4.0, 3000.0, eps_r=6.0)
    assert uhf["single_antenna_reach_m"] > vhf["single_antenna_reach_m"]
    assert uhf["antennas_required"] <= vhf["antennas_required"]
    assert len(uhf["positions_m"]) == uhf["antennas_required"]


# ------------------------------------------------------------- API layer
def test_leaky_feeder_api():
    body = {"freq_mhz": 450.0, "length_m": 2000.0,
            "cable_atten_db_per_100m": 4.0, "amp_gain_db": 30.0,
            "tx_power_dbm": 20.0, "rx_sensitivity_dbm": -95.0}
    resp = client.post("/api/indoor/leaky-feeder", json=body)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "served_length_fraction" in data and "worst_gap_m" in data
    assert data["amps_required"] >= 1


def test_tunnel_das_api():
    resp = client.get("/api/indoor/tunnel-das",
                      params={"freq_mhz": 450.0, "length_m": 2500.0,
                              "wall": "concrete"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["antennas_required"] >= 1
    assert data["single_antenna_reach_m"] > 0
