"""Tests: MSI pattern parsing, pattern-driven coverage, multi-site composite,
and DEM disk-cache eviction."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.rf.antenna import parse_msi, pattern_attenuation
from app.services.terrain.coverage import CoverageEngine, composite_best_server
from app.services.terrain.fusion import TerrainFusionService


def _msi_text(gain="17.5 dBd", h_bw=65, v_bw=8):
    """Synthesize a plausible sector antenna MSI file."""
    lines = ["NAME TESTANT-01", f"GAIN {gain}", "TILT ELECTRICAL 2",
             "HORIZONTAL 360"]
    for a in range(360):
        d = min(abs(a), 360 - a)                      # offset from boresight 0
        lines.append(f"{a} {min(12.0 * (d / h_bw) ** 2, 30.0):.2f}")
    lines.append("VERTICAL 360")
    for a in range(360):
        d = min(abs(a), 360 - a)
        lines.append(f"{a} {min(12.0 * (d / v_bw) ** 2, 30.0):.2f}")
    return "\n".join(lines)


# ------------------------------------------------------------- MSI parsing
def test_parse_msi_and_attenuation():
    p = parse_msi(_msi_text())
    assert p["name"] == "TESTANT-01"
    assert p["gain_dbi"] == pytest.approx(17.5 + 2.15)   # dBd -> dBi
    assert p["electrical_tilt_deg"] == 2.0
    assert len(p["horizontal"]) == 360 and len(p["vertical"]) == 360
    # Boresight ~0 dB; the back of the antenna heavily attenuated.
    att0 = pattern_attenuation(p, np.array([0.0]), np.array([0.0]))
    att180 = pattern_attenuation(p, np.array([180.0]), np.array([0.0]))
    assert att0[0] == pytest.approx(0.0, abs=0.1)
    assert att180[0] >= 25.0


def test_parse_msi_rejects_incomplete():
    with pytest.raises(ValueError):
        parse_msi("NAME X\nGAIN 10 dBi\nHORIZONTAL 360\n" +
                  "\n".join(f"{a} 0" for a in range(360)))


# ------------------------------------------- pattern-driven coverage engine
def test_coverage_with_measured_pattern(fake_store):
    engine = CoverageEngine(TerrainFusionService(store=fake_store))
    from app.services.rf.technologies import get_technology
    tech = get_technology("gsm900")
    pattern = parse_msi(_msi_text())
    east = engine.compute_polar(47.0, 15.0, dict(tech), radius_m=8000,
                                n_radials=72, n_steps=30,
                                antenna_azimuth_deg=90.0,
                                antenna_pattern=pattern)
    # Strongest radial should point east (index 18 of 72 = 90 deg).
    per_radial = east["rx_power"].max(axis=1)
    assert abs(int(np.argmax(per_radial)) - 18) <= 2
    # The back (270 deg, index 54) must be much weaker than boresight.
    assert per_radial[18] - per_radial[54] >= 20.0


# ------------------------------------------------------ multi-site composite
def test_composite_best_server(fake_store):
    engine = CoverageEngine(TerrainFusionService(store=fake_store))
    from app.services.rf.technologies import get_technology
    tech = get_technology("gsm900")
    sites = []
    for i, (la, lo) in enumerate([(47.0, 15.0), (47.0, 15.12)]):
        polar = engine.compute_polar(la, lo, dict(tech), radius_m=6000,
                                     n_radials=48, n_steps=30)
        sites.append({"lat": la, "lon": lo, "name": f"S{i+1}",
                      "radius_m": 6000.0, "polar": polar})
    png, bounds, stats, served_frac, sinr = composite_best_server(
        sites, raster_px=192)
    assert png[:4] == b"\x89PNG"
    assert sinr is None                          # no noise floor given
    assert len(stats) == 2
    assert 0.0 < served_frac <= 1.0
    shares = [s["best_server_share"] for s in stats]
    assert sum(shares) == pytest.approx(1.0, abs=0.01)
    assert min(shares) > 0.2                     # both sites win territory
    (s, w), (n, e) = bounds
    assert w < 15.0 and e > 15.12                # union bbox spans both


def test_composite_sinr_analysis(fake_store):
    """Co-channel SINR: overlap zones must degrade vs an isolated site."""
    engine = CoverageEngine(TerrainFusionService(store=fake_store))
    from app.services.rf.technologies import get_technology
    tech = get_technology("gsm900")
    noise = -174.0 + 10.0 * np.log10(10e6) + 7.0          # 10 MHz / 7 dB NF

    def run(site_lls):
        sites = []
        for i, (la, lo) in enumerate(site_lls):
            polar = engine.compute_polar(la, lo, dict(tech), radius_m=6000,
                                         n_radials=48, n_steps=30)
            sites.append({"lat": la, "lon": lo, "name": f"S{i+1}",
                          "radius_m": 6000.0, "polar": polar})
        return composite_best_server(sites, raster_px=160, noise_dbm=noise)

    *_, sinr_two = run([(47.0, 15.0), (47.0, 15.05)])     # heavy overlap
    *_, sinr_one = run([(47.0, 15.0)])
    assert sinr_two is not None and sinr_one is not None
    assert sinr_two["png"][:4] == b"\x89PNG"
    assert sinr_two["noise_dbm"] == pytest.approx(noise, abs=0.1)
    # Alone, the site is only noise-limited; a co-channel neighbor a few km
    # away must degrade the SINR statistics (means include both cells'
    # signal-dominated centers, so the drop is a few dB, not tens).
    assert sinr_two["mean_db"] < sinr_one["mean_db"] - 2.0
    assert sinr_two["ge_6db_fraction"] < sinr_one["ge_6db_fraction"]
    assert sinr_two["edge_fraction"] >= sinr_one["edge_fraction"]


# ----------------------------------------------------------------- API layer
@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion", TerrainFusionService(store=fake_store))
    return TestClient(app)


def test_antenna_and_multisite_api(client):
    up = client.post("/api/rf/antenna",
                     files={"file": ("k742.msi", _msi_text().encode(), "text/plain")})
    assert up.status_code == 200, up.text
    ant = up.json()
    assert ant["gain_dbi"] == pytest.approx(19.65, abs=0.01)
    assert 50 <= ant["h_beamwidth_deg"] <= 80

    listed = client.get("/api/rf/antennas").json()["antennas"]
    assert any(a["antenna_id"] == ant["antenna_id"] for a in listed)

    resp = client.post("/api/rf/coverage/multi", json={
        "sites": [
            {"lat": 47.0, "lon": 15.0, "name": "Alpha", "antenna_azimuth_deg": 90},
            {"lat": 47.0, "lon": 15.12, "name": "Bravo", "antenna_azimuth_deg": 270},
        ],
        "technology": "gsm900", "radius_km": 6,
        "antenna_id": ant["antenna_id"],
        "n_radials": 48, "n_steps": 30,
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["legend"]) == 2
    assert body["legend"][0]["label"] == "Alpha"
    assert len(body["stats"]["sites"]) == 2
    png = client.get(body["png_url"])
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"


# ----------------------------------------------------------- cache eviction
def test_dem_disk_cache_eviction(tmp_path):
    from app.services.dem.tiles import TerrariumTileStore
    store = TerrariumTileStore(cache_dir=tmp_path, zoom=12)
    # Fabricate 30 fake cached tiles of 10 KB each.
    for i in range(30):
        p = tmp_path / "12" / str(i) / "0.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * 10_240)
    removed = store.evict_disk_cache(budget_mb=0.1)   # 100 KB budget
    remaining = len(list(tmp_path.glob("*/*/*.png")))
    assert removed == 30 - remaining
    assert remaining * 10_240 <= 0.1 * 1024 * 1024 + 10_240
