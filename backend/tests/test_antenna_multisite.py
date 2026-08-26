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


# ------------------------------------------- per-transmitter radio parameters
def test_cluster_sites_can_differ_in_every_radio_parameter(client):
    """A cluster study must be able to describe the customer's actual network.

    Regression: /coverage/multi cloned ONE technology dict across every site
    (`dict(tech)` in each loop), and SiteIn carried only lat/lon/name/azimuth/
    downtilt. A real estate - an 800 MHz macro layer, a 3.5 GHz capacity layer,
    a 400 MHz PMR overlay, each with its own power and mast height - was
    therefore inexpressible, and the composite described a network that does
    not exist. Six committee personas independently called this a blocker.
    """
    body = {"technology": "gsm900", "radius_km": 4, "n_radials": 36,
            "n_steps": 20, "raster_px": 160, "sites": [
                {"lat": 47.00, "lon": 15.00, "name": "Macro 800",
                 "freq_mhz": 806, "tx_power_dbm": 46, "h_bs_m": 30},
                {"lat": 47.03, "lon": 15.03, "name": "Small cell n78",
                 "freq_mhz": 3500, "tx_power_dbm": 33, "h_bs_m": 12},
            ]}
    r = client.post("/api/rf/coverage/multi", json=body)
    assert r.status_code == 200, r.text
    sites = r.json()["stats"]["sites"]
    assert len(sites) == 2

    # The response says what each transmitter actually ran on, so an override
    # cannot be confused with one that was silently ignored.
    macro = next(s["resolved"] for s in sites if s["name"] == "Macro 800")
    small = next(s["resolved"] for s in sites if s["name"] == "Small cell n78")
    assert (macro["freq_mhz"], macro["tx_power_dbm"], macro["h_bs_m"]) == (806, 46, 30)
    assert (small["freq_mhz"], small["tx_power_dbm"], small["h_bs_m"]) == (3500, 33, 12)

    # And the physics used them: 806 MHz at 46 dBm from 30 m reaches much
    # further than 3.5 GHz at 33 dBm from 12 m, so it serves most of the disc.
    share = {s["name"]: s["best_server_share"] for s in sites}
    assert share["Macro 800"] > share["Small cell n78"]


def test_cluster_without_per_site_parameters_is_unchanged(client):
    """Backward compatibility: a caller sending only lat/lon/name gets exactly
    the preset it always did, on every site."""
    body = {"technology": "gsm900", "radius_km": 4, "n_radials": 36,
            "n_steps": 20, "raster_px": 160, "sites": [
                {"lat": 47.0, "lon": 15.0, "name": "A"},
                {"lat": 47.02, "lon": 15.02, "name": "B"},
            ]}
    r = client.post("/api/rf/coverage/multi", json=body)
    assert r.status_code == 200, r.text
    preset = r.json()["technology"]
    for s in r.json()["stats"]["sites"]:
        assert s["resolved"]["freq_mhz"] == preset["freq_mhz"]
        assert s["resolved"]["tx_power_dbm"] == preset["tx_power_dbm"]


# --------------------------------------------------- site inventory as CSV
def test_site_csv_round_trips_and_explains_every_rejection(client):
    """An operator's estate arrives as a CSV from their OSS. Clicking 200
    sites onto a map one at a time is not an onboarding path, and a row
    dropped in silence is worse than one refused out loud."""
    csv = (b"name,lat,lon,freq_mhz,tx_power_dbm,h_bs_m,antenna_azimuth_deg\n"
           b"Macro A,47.0,15.0,806,46,30,120\n"
           b"Small B,47.03,15.03,3500,33,12,\n"
           b"Broken,not-a-number,15.0,,,,\n"
           b"Off world,999,15.0,,,,\n"
           b"Bad power,47.1,15.1,900,oops,,\n")
    r = client.post("/api/rf/sites/parse-csv",
                    files={"file": ("sites.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 2
    assert body["sites"][0]["name"] == "Macro A"
    assert body["sites"][0]["freq_mhz"] == 806
    assert body["sites"][0]["antenna_azimuth_deg"] == 120
    # A blank cell inherits rather than becoming zero.
    assert body["sites"][1]["antenna_azimuth_deg"] is None

    # Every bad row is reported with its line number and a reason.
    reasons = {k["line"]: k["reason"] for k in body["skipped"]}
    assert set(reasons) == {4, 5, 6}
    assert "lat/lon" in reasons[4]
    assert "out of range" in reasons[5]
    assert "tx_power_dbm" in reasons[6]

    # Round trip through the exporter is lossless.
    exported = client.post("/api/rf/sites/export-csv", json=body["sites"])
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    again = client.post("/api/rf/sites/parse-csv",
                        files={"file": ("s.csv", exported.content, "text/csv")})
    assert again.json()["sites"] == body["sites"]

    # The parsed sites drop straight into a cluster study.
    study = client.post("/api/rf/coverage/multi", json={
        "technology": "gsm900", "radius_km": 4, "n_radials": 36,
        "n_steps": 20, "raster_px": 128, "sites": body["sites"]})
    assert study.status_code == 200, study.text


def test_site_csv_refuses_a_file_without_coordinates(client):
    r = client.post("/api/rf/sites/parse-csv", files={
        "file": ("x.csv", b"site,band\nA,800\n", "text/csv")})
    assert r.status_code == 422
    assert "lat" in r.json()["detail"]
