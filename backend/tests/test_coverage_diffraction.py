"""The area-coverage kernel must diffract like the documented method.

Coverage is the deliverable a planner signs. Its kernel used to take only the
single strongest knife edge on each TX->step sub-path, while README and the
profile/ITM paths advertised Deygout multi-edge. Measured against
``deygout_loss_db`` on synthetic terrain that under-predicted loss by ~15 dB
over one ridge and ~30 dB over three - optimistic, in exactly the multi-ridge
terrain a coverage study exists to characterise, and inherited by every
derived product (best-server, SINR, throughput, site search, batch CPE).

These tests pin the kernel to the scalar reference.
"""
import numpy as np
import pytest

from app.services.rf.models import deygout_loss_db, ke_loss_array
from app.services.rf.physics import K_FACTOR_DEFAULT, apply_earth_curvature
from app.services.terrain.coverage import C_LIGHT, diffraction_loss_grid

FREQ_MHZ = 900.0
LAM = C_LIGHT / (FREQ_MHZ * 1e6)
TX_H = RX_H = 30.0


def profile(ridges, n=201, span_m=30_000.0, base=100.0):
    """Flat ground at `base` with single-sample knife edges at `ridges`."""
    d = np.linspace(0.0, span_m, n)
    raw = np.full_like(d, base)
    for idx, height in ridges:
        raw[idx] += height
    return d, raw


def kernel_loss(d, raw):
    """Loss the coverage kernel predicts for the full TX->far-end path.

    The kernel curves the profile itself (it adds the earth bulge per
    sub-path), so it is handed the RAW ground profile.
    """
    grid = diffraction_loss_grid(raw[None, :], d, e_tx=raw[0] + TX_H,
                                 h_ut=RX_H, lam=LAM, k=K_FACTOR_DEFAULT)
    return float(grid[0, -1])


def reference_loss(d, raw):
    """The scalar reference used by the profile and ITM paths."""
    return deygout_loss_db(d, apply_earth_curvature(d, raw),
                           TX_H, RX_H, FREQ_MHZ)


@pytest.mark.parametrize("name,ridges", [
    ("flat", []),
    ("single ridge", [(150, 150.0)]),
    ("two ridges", [(60, 150.0), (140, 150.0)]),
    ("asymmetric pair", [(30, 200.0), (170, 90.0)]),
    ("near and far", [(20, 120.0), (180, 120.0)]),
    ("tall midpath", [(100, 300.0)]),
])
def test_kernel_matches_the_scalar_reference(name, ridges):
    """Up to two obstructing edges the two constructions coincide exactly."""
    d, raw = profile(ridges)
    assert kernel_loss(d, raw) == pytest.approx(reference_loss(d, raw), abs=1.0)


def test_three_ridges_no_longer_wildly_optimistic():
    """With three or more obstructions the scalar reference spends its shared
    3-edge budget left-first, while the kernel takes the principal edge plus
    one secondary per side. The constructions genuinely differ there, so this
    pins the property that matters: the kernel is close, and nowhere near the
    15-30 dB optimism of the single-edge kernel it replaced."""
    d, raw = profile([(50, 150.0), (100, 150.0), (150, 150.0)])
    ref, got = reference_loss(d, raw), kernel_loss(d, raw)
    assert got == pytest.approx(ref, abs=9.0)
    assert ref - got < 9.0, "kernel must not be far optimistic vs the reference"

    # The old kernel: strongest single edge only. Kept here as the regression
    # this test exists to prevent.
    single = _single_edge_loss(d, raw)
    assert ref - single > 25.0, "sanity: the old kernel really was that optimistic"
    assert got - single > 20.0, "the fix must recover most of that loss"


def test_more_obstructions_never_reduce_predicted_loss():
    """Monotonicity: adding a ridge to a path cannot make it propagate better.
    A kernel that picks its edges badly can violate this."""
    d, one = profile([(150, 150.0)])
    _, two = profile([(60, 150.0), (150, 150.0)])
    _, three = profile([(60, 150.0), (100, 150.0), (150, 150.0)])
    losses = [kernel_loss(d, p) for p in (one, two, three)]
    assert losses[0] <= losses[1] + 1e-6 <= losses[2] + 1e-6, losses


def test_line_of_sight_path_has_no_diffraction_loss():
    """A clear path over flat ground must not invent loss."""
    d = np.linspace(0.0, 5_000.0, 101)
    raw = np.zeros_like(d)
    grid = diffraction_loss_grid(raw[None, :], d, e_tx=200.0, h_ut=200.0,
                                 lam=LAM, k=K_FACTOR_DEFAULT)
    assert float(grid[0, -1]) == pytest.approx(0.0, abs=0.5)


def test_loss_grows_along_a_radial_past_an_obstruction():
    """Every step beyond a ridge should be shadowed, not just the far end."""
    d, raw = profile([(100, 200.0)])
    grid = diffraction_loss_grid(raw[None, :], d, e_tx=raw[0] + TX_H,
                                 h_ut=RX_H, lam=LAM, k=K_FACTOR_DEFAULT)
    before, after = grid[0, 90], grid[0, 120]
    assert before < 1.0, "no loss before the ridge"
    assert after > 10.0, "shadow behind the ridge"


def _single_edge_loss(d, raw):
    """The retired kernel: strongest single knife edge, for regression only."""
    e = apply_earth_curvature(d, raw).copy()
    e[0] += TX_H
    e[-1] += RX_H
    di = d[-1]
    j = np.arange(1, len(d) - 1)
    dj, d2 = d[j], di - d[j]
    los = e[0] + (e[-1] - e[0]) * dj / di
    v = (e[j] - los) * np.sqrt(2 * di / (LAM * dj * d2))
    return float(ke_loss_array(np.array([v.max()]))[0])
