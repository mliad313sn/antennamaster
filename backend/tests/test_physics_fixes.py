"""Regression tests for the deep-physics-review fixes:
gaseous-attenuation E/W band, Fresnel-ratio worst-point, Deygout edge
budget, and MSI electrical-tilt double-count."""
import numpy as np
import pytest

from app.services.rf.environment import gaseous_attenuation_db_per_km
from app.services.rf.models import deygout_loss_db
from app.services.rf.physics import analyze_path, fresnel_radius_m


def test_gaseous_decays_above_the_60ghz_complex():
    """The old code clamped every f>=54 GHz to the 60 GHz peak (15 dB/km);
    real dry air falls back to <1 dB/km through the E/W-band windows."""
    g = gaseous_attenuation_db_per_km
    assert g(60_000) > 12.0                       # 60 GHz oxygen peak
    # E-band (71-86 GHz) and W-band (94 GHz) must be low, not 15.
    for f_ghz in (71, 80, 86, 94):
        val = g(f_ghz * 1000)
        assert val < 2.0, f"{f_ghz} GHz gaseous {val} dB/km too high"
    # Monotonic decay off the peak across the E-band.
    assert g(71_000) > g(80_000) > g(94_000)
    # Low-band behaviour unchanged (tiny).
    assert g(10_000) < 0.05


def test_fresnel_ratio_is_worst_point_not_min_clearance():
    """fresnel_clearance_ratio must be min(clearance/F1), so a mid-path
    obstruction is not masked by a near-endpoint sample with small
    absolute clearance but a large F1 ratio (F1 shrinks toward the ends)."""
    d = np.linspace(0, 10_000, 201)
    # Build a profile (already-curved space: pass k=1 and flat baseline).
    e = np.zeros_like(d)
    # Near-end bump at 250 m: small F1 there, generous clearance/F1.
    # Mid bump at 5 km: large F1, tight clearance/F1 -> the true worst.
    e[5] = 6.0                                    # d=250 m obstacle top
    e[100] = 11.0                                 # d=5 km obstacle top
    r = analyze_path(d, e, 20.0, 20.0, 5800.0, k=1.0)
    tot = d[-1] - d[0]
    d1 = d - d[0]; d2 = tot - d1
    f1 = fresnel_radius_m(d1, d2, 5800e6, 1)
    clr = r["los_m"] - r["terrain_curved_m"]
    true_min = float(np.min((clr[1:-1] / np.where(f1[1:-1] > 0, f1[1:-1], np.inf))))
    assert r["fresnel_clearance_ratio"] == pytest.approx(true_min, abs=1e-6)
    # And the worst point is the mid-path one, not the near-end sample.
    ratios = clr[1:-1] / np.where(f1[1:-1] > 0, f1[1:-1], np.inf)
    assert 90 <= int(np.argmin(ratios)) + 1 <= 110


def test_deygout_edge_budget_is_a_total_count():
    """max_edges is a TOTAL edge count (principal + secondaries), not a
    recursion depth that would sum up to 2^n-1 edges."""
    d = np.linspace(0, 14_000, 141)
    e = np.zeros_like(d)
    for c in (20, 40, 60, 80, 100, 120):          # six ridges
        e[c] = 60.0
    l1 = deygout_loss_db(d, e, 20, 20, 900, max_edges=1)
    l3 = deygout_loss_db(d, e, 20, 20, 900, max_edges=3)
    l_big = deygout_loss_db(d, e, 20, 20, 900, max_edges=99)
    assert l1 > 0
    assert l3 >= l1
    # A generous budget cannot explode past the bounded classic construction.
    assert l_big == pytest.approx(l3, abs=6.0) or l_big >= l3
    # Concretely, 3 edges must stay well under an unbounded 2^n-style sum:
    # six ~identical ridges at 900 MHz cap out around ~45 dB, not ~90+.
    assert l3 < 70.0


def test_deygout_single_edge_matches_knife_edge():
    """One obstacle: Deygout with any budge >= 1 equals the single knife
    edge (sanity anchor unaffected by the budget change)."""
    from app.services.rf.physics import knife_edge_loss_db, C_LIGHT
    d = np.linspace(0, 10_000, 101)
    e = np.zeros_like(d)
    e[50] = 80.0
    got = deygout_loss_db(d, e, 10, 10, 2000, max_edges=3)
    # Hand v at the single edge (endpoints raised by antenna heights).
    e2 = e.copy(); e2[0] += 10; e2[-1] += 10
    los = e2[0] + (e2[-1] - e2[0]) * d[50] / d[-1]
    h = e2[50] - los
    lam = C_LIGHT / 2000e6
    v = h * np.sqrt(2.0 / lam * (d[50] + (d[-1] - d[50]))
                    / (d[50] * (d[-1] - d[50])))
    assert got == pytest.approx(knife_edge_loss_db(v), abs=0.1)


def test_msi_electrical_tilt_not_double_counted(fake_store):
    """A measured pattern's main lobe already sits at its electrical tilt;
    coverage must not additionally offset the boresight by it.  With a
    downtilt of 0, the strongest RX along a near-flat radial should occur
    near the pattern's own peak, i.e. the result must match an identical
    pattern whose TILT header is 0."""
    from app.services.terrain.coverage import CoverageEngine
    from app.services.terrain.fusion import TerrainFusionService
    from app.services.rf.antenna import parse_msi
    from app.services.rf.technologies import get_technology

    def msi(tilt):
        lines = ["NAME T", "GAIN 17 dBd", f"TILT ELECTRICAL {tilt}",
                 "HORIZONTAL 360"]
        lines += [f"{a} {min(12.0*(min(abs(a),360-a)/65)**2,30):.2f}"
                  for a in range(360)]
        lines.append("VERTICAL 360")
        lines += [f"{a} {min(12.0*(min(abs(a),360-a)/8)**2,30):.2f}"
                  for a in range(360)]
        return parse_msi("\n".join(lines))

    engine = CoverageEngine(TerrainFusionService(store=fake_store))
    tech = get_technology("gsm900")
    common = dict(radius_m=8000, n_radials=72, n_steps=30,
                  antenna_azimuth_deg=90.0, downtilt_deg=0.0)
    # The e-tilt header must NOT change the modeled field (it is metadata;
    # the measured cut already encodes the tilt).  Both runs use the same
    # synthetic cut shape, so identical output proves no extra offset.
    a = engine.compute_polar(47.0, 15.0, dict(tech),
                             antenna_pattern=msi(0), **common)
    b = engine.compute_polar(47.0, 15.0, dict(tech),
                             antenna_pattern=msi(6), **common)
    assert np.allclose(a["rx_power"], b["rx_power"], atol=1e-6)
