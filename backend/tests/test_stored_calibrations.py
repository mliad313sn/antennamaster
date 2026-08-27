"""A model tuning should be a named site asset, not a blob you paste around.

`/api/rf/calibrate` fits a correction from drive-test data and hands back the
coefficients. Applying it to the next study meant carrying that object around
by hand, which means: nobody knows which tuning a filed study used, nobody can
reuse last quarter's fit, and there is nothing on screen tying "+6.2 dB" to
the measurements that justify it.
"""
import time

import pytest
from fastapi.testclient import TestClient

import app.api.routes_rf as routes_rf
import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.terrain.fusion import TerrainFusionService

FIT = {"mode": "offset", "offset_db": -6.2,
       "slope_intercept_db": 0.0, "slope_per_decade_db": 0.0}
BODY = {"lat": 47.0, "lon": 15.0, "technology": "pmr446", "radius_km": 4,
        "n_radials": 36, "n_steps": 20, "resolution_m": 400}


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    fusion = TerrainFusionService(store=fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion", fusion)
    monkeypatch.setattr(routes_rf, "resolve_fusion", lambda surface=False: fusion)
    return TestClient(app)


def _account(client, tag="c"):
    r = client.post("/api/auth/register", json={
        "email": f"{tag}{time.time_ns()}@x.io", "password": "hunter22secure",
        "role": "field", "org_name": ""})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _save(client, hdrs, name="Graz quarry", technology="pmr446", **over):
    r = client.post("/api/rf/calibrations", headers=hdrs, json={
        "name": name, "technology": technology, "calibration": FIT,
        "n_points": 240, "rms_before_db": 11.4, "rms_after_db": 5.1,
        "residual_std_db": 5.0, "note": "March drive test, quarry haul road",
        **over})
    assert r.status_code == 200, r.text
    return r.json()["calibration"]


def test_a_tuning_keeps_the_evidence_that_justifies_it(client):
    """The coefficients alone are not credible. What makes "+6.2 dB"
    defensible is 240 points and an RMS that fell from 11.4 to 5.1 dB — so
    that travels with the fit, not in someone's memory."""
    hdrs = _account(client)
    saved = _save(client, hdrs)

    got = client.get(f"/api/rf/calibrations/{saved['id']}", headers=hdrs)
    assert got.status_code == 200
    body = got.json()["calibration"]
    assert body["name"] == "Graz quarry"
    assert body["n_points"] == 240
    assert body["rms_before_db"] == 11.4 and body["rms_after_db"] == 5.1
    assert body["calibration"]["offset_db"] == -6.2
    assert "drive test" in body["note"]
    # The owner id is internal and never leaves.
    assert "user_id" not in body


def test_a_study_can_name_a_tuning_instead_of_pasting_its_numbers(client):
    hdrs = _account(client)
    saved = _save(client, hdrs)

    plain = client.post("/api/rf/coverage", json=BODY, headers=hdrs)
    tuned = client.post("/api/rf/coverage", headers=hdrs,
                        json={**BODY, "calibration_id": saved["id"]})
    assert plain.status_code == 200 and tuned.status_code == 200, tuned.text

    # -6.2 dB of correction has to actually reach the field.
    assert tuned.json()["stats"]["max_rx_power_dbm"] == pytest.approx(
        plain.json()["stats"]["max_rx_power_dbm"] - 6.2, abs=0.3)


def test_the_filed_study_records_which_tuning_was_applied(client):
    """The point of naming it: a study of record that says "calibrated" and
    cannot say *by what* is not much of a record."""
    hdrs = _account(client)
    saved = _save(client, hdrs)
    cid = client.post("/api/rf/coverage", headers=hdrs,
                      json={**BODY, "calibration_id": saved["id"]}
                      ).json()["coverage_id"]

    rec = client.get(f"/api/rf/coverage/{cid}/record", headers=hdrs).json()
    assert rec["request"]["calibration_id"] == saved["id"]


def test_reusing_a_fit_across_bands_is_allowed_but_never_silent(client):
    """A planner may legitimately reuse a site's clutter correction on
    another band. Applying it without a word would be the tool asserting a
    physical claim the measurements do not support."""
    hdrs = _account(client)
    saved = _save(client, hdrs, technology="pmr446")

    r = client.post("/api/rf/coverage", headers=hdrs,
                    json={**BODY, "technology": "gsm900",
                          "calibration_id": saved["id"]})
    assert r.status_code == 200, r.text
    assert any("fitted for a different technology" in w
               for w in r.json()["warnings"])


def test_one_tenants_tuning_is_not_visible_or_usable_by_another(client):
    """A calibration says how a customer's own site actually behaves —
    competitively meaningful, and derived from their measurements."""
    mine, theirs = _account(client, "m"), _account(client, "t")
    saved = _save(client, mine, name="Confidential quarry")

    listing = client.get("/api/rf/calibrations", headers=theirs).json()
    assert all(c["name"] != "Confidential quarry"
               for c in listing["calibrations"])
    # 404, not 403: an id must not confirm that the tuning exists.
    assert client.get(f"/api/rf/calibrations/{saved['id']}",
                      headers=theirs).status_code == 404
    assert client.delete(f"/api/rf/calibrations/{saved['id']}",
                         headers=theirs).status_code == 404
    # ...and a study cannot borrow it by id either.
    assert client.post("/api/rf/coverage", headers=theirs,
                       json={**BODY, "calibration_id": saved["id"]}
                       ).status_code == 404
    # The owner still has it after all that.
    assert client.get(f"/api/rf/calibrations/{saved['id']}",
                      headers=mine).status_code == 200


def test_a_tuning_can_be_retired(client):
    hdrs = _account(client)
    saved = _save(client, hdrs)
    assert client.delete(f"/api/rf/calibrations/{saved['id']}",
                         headers=hdrs).status_code == 200
    assert client.get(f"/api/rf/calibrations/{saved['id']}",
                      headers=hdrs).status_code == 404
