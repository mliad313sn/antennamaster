"""Optimization-safety gate: the float32 chunked diffraction path must match
a straightforward float64 reference implementation. Guards every future
performance refactor against silently changing the physics."""
import numpy as np
import pytest

from app.services.rf.models import ke_loss_array
from app.services.rf.physics import EARTH_RADIUS_M
from app.services.rf.technologies import get_technology
from app.services.terrain.coverage import CoverageEngine
from app.services.terrain.fusion import TerrainFusionService

C_LIGHT = 299_792_458.0


def _reference_diffraction(elev, dist, tx_elev, h_bs, h_ut, freq_mhz, k):
    """Unoptimized float64 per-radial single-strongest-edge diffraction."""
    lam = C_LIGHT / (freq_mhz * 1e6)
    n_radials, n_steps = elev.shape
    d = dist
    out = np.zeros((n_radials, n_steps))
    e_tx = tx_elev + h_bs
    for r in range(n_radials):
        for i in range(n_steps):
            d_i = d[i]
            e_rx = elev[r, i] + h_ut
            v_max = -np.inf
            for j in range(i):
                d_j = d[j]
                d2 = d_i - d_j
                bulge = d_j * d2 / (2.0 * k * EARTH_RADIUS_M)
                los = e_tx + (e_rx - e_tx) * d_j / d_i
                v = ((elev[r, j] + bulge - los)
                     * np.sqrt(2.0 * d_i / (lam * max(d_j, 1.0) * d2)))
                v_max = max(v_max, v)
            out[r, i] = ke_loss_array(np.array([v_max]))[0]
    return out


def test_float32_diffraction_matches_float64_reference(fake_store):
    engine = CoverageEngine(TerrainFusionService(store=fake_store))
    tech = get_technology("gsm900")
    # Small but non-trivial polar field over the synthetic ramp world.
    polar = engine.compute_polar(47.0, 15.0, dict(tech),
                                 radius_m=8000, n_radials=12, n_steps=25)

    # Rebuild the exact same inputs the engine used.
    from pyproj import Geod
    geod = Geod(ellps="WGS84")
    az = polar["az"]
    dist = polar["dist"]
    az_g, dist_g = np.meshgrid(az, dist, indexing="ij")
    lons, lats, _ = geod.fwd(np.full(az_g.size, 15.0), np.full(az_g.size, 47.0),
                             az_g.ravel(), dist_g.ravel())
    fusion = TerrainFusionService(store=fake_store)
    elev = fusion.fused_elevations(np.asarray(lats), np.asarray(lons),
                                   None, None)[0].reshape(len(az), len(dist))
    tx_elev = float(fusion.fused_elevations(np.array([47.0]), np.array([15.0]),
                                            None, None)[0][0])

    ref = _reference_diffraction(elev, dist, tx_elev, tech["h_bs_m"],
                                 tech["h_ut_m"], tech["freq_mhz"], 4.0 / 3.0)

    # Recover the engine's diffraction loss from its rx_power output.
    from app.services.rf.models import path_loss_db
    pl, _ = path_loss_db(tech["model"], dist_g.ravel(), tech["freq_mhz"],
                         tech["h_bs_m"], tech["h_ut_m"], tech["environment"])
    pl = pl.reshape(len(az), len(dist))
    from app.services.rf.environment import gaseous_attenuation_db_per_km
    gas = gaseous_attenuation_db_per_km(tech["freq_mhz"]) * dist / 1000.0
    eirp = (tech["tx_power_dbm"] + tech["tx_gain_dbi"] + tech["rx_gain_dbi"]
            - tech["losses_db"])
    engine_diff = eirp - pl - gas[None, :] - polar["rx_power"]

    # float32 vs float64 agreement: 0.05 dB is far below any planning margin.
    assert np.max(np.abs(engine_diff - ref)) < 0.05


def test_float32_no_spurious_diffraction_on_flat_world(fake_store):
    """On the smooth ramp world with a tall mast, losses stay near zero -
    float32 rounding must not fabricate obstacles."""
    engine = CoverageEngine(TerrainFusionService(store=fake_store))
    tech = dict(get_technology("gsm900"), h_bs_m=80.0)
    polar = engine.compute_polar(47.0, 15.0, tech, radius_m=3000,
                                 n_radials=24, n_steps=30)
    # Fake world is a gentle slope: with an 80 m mast every step is LOS.
    spread = polar["rx_power"].max(axis=0) - polar["rx_power"].min(axis=0)
    assert float(spread.max()) < 3.0     # only smooth terrain variation
