"""A coverage study has to be defensible months later, by someone else.

The plot goes into a licence application, a tender response, a safety case —
documents read long after the fact and sometimes disputed. What was stored
with each raster was its bounds, the mast position, the radius and the
headline statistics: enough to redraw the picture, nothing like enough to
defend it. The frequency, the model, the antenna, the margins, the clutter and
weather assumptions, the terrain source and the engine versions all vanished
when the request finished, so two studies a month apart could differ by 20 dB
with nothing on the artefact to say why.
"""
import pytest
from fastapi.testclient import TestClient

import app.api.routes_rf as routes_rf
import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.saas import study_record
from app.services.terrain.fusion import TerrainFusionService

BODY = {"lat": 47.0, "lon": 15.0, "technology": "pmr446", "radius_km": 5,
        "n_radials": 36, "n_steps": 30, "resolution_m": 400,
        "shadow_margin_db": 8.0, "clutter_pct": 50.0}


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    fusion = TerrainFusionService(store=fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion", fusion)
    monkeypatch.setattr(routes_rf, "resolve_fusion", lambda surface=False: fusion)
    return TestClient(app)


def _run(client, **over):
    r = client.post("/api/rf/coverage", json={**BODY, **over})
    assert r.status_code == 200, r.text
    return r.json()


def test_the_record_holds_every_input_not_just_the_ones_you_can_see(client):
    cid = _run(client)["coverage_id"]
    rec = client.get(f"/api/rf/coverage/{cid}/record")
    assert rec.status_code == 200, rec.text
    body = rec.json()

    req = body["request"]
    # The assumptions that move the answer by tens of dB and leave no trace on
    # the picture are exactly the ones that have to be in the record.
    assert req["shadow_margin_db"] == 8.0
    assert req["clutter_pct"] == 50.0
    assert req["technology"] == "pmr446"
    assert req["radius_km"] == 5

    prov = body["provenance"]
    assert prov["app_version"]
    assert prov["terrain_source"], "which DEM produced this is part of the claim"
    assert "itm" in prov["engines"]


def test_the_digest_is_citable_and_specific(client):
    """Short enough for a report footer, specific enough that two studies
    carrying it ran the same way."""
    a = _run(client)
    b = _run(client)                                   # same inputs
    c = _run(client, shadow_margin_db=12.0)            # one assumption moved

    assert len(a["study_digest"]) == 16
    assert a["study_digest"] == b["study_digest"]
    assert c["study_digest"] != a["study_digest"]


def test_the_digest_does_not_depend_on_dict_ordering():
    """Otherwise two identical studies get different digests and a reader
    concludes something changed when nothing did."""
    one = study_record.build({"a": 1, "b": {"x": 1, "y": 2}})
    two = study_record.build({"b": {"y": 2, "x": 1}, "a": 1})
    assert one["digest"] == two["digest"]


def test_rerunning_answers_does_it_still_say_that(client):
    """The question a reviewer actually asks — after a DEM refresh, a model
    fix or a release — is not "what did you run" but "does it still hold"."""
    original = _run(client)
    r = client.post(f"/api/rf/coverage/{original['coverage_id']}/rerun")
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["reproduced"] is True
    assert body["changed_stats"] == {}
    assert body["build_changed"] is False
    assert body["original"]["digest"] == original["study_digest"]


def test_a_rerun_is_a_new_study_and_never_edits_the_old_one(client):
    """An edited study of record is not one."""
    original = _run(client)
    cid = original["coverage_id"]
    before = client.get(f"/api/rf/coverage/{cid}/record").json()

    r = client.post(f"/api/rf/coverage/{cid}/rerun").json()
    assert r["rerun"]["coverage_id"] != cid

    after = client.get(f"/api/rf/coverage/{cid}/record").json()
    assert after == before, "the filed study was modified by a re-run"
    # ...and the new one is a full study of record in its own right.
    fresh = client.get(f"/api/rf/coverage/{r['rerun']['coverage_id']}/record")
    assert fresh.status_code == 200
    assert fresh.json()["digest"] == r["rerun"]["study_digest"]


def test_a_study_from_another_tenant_is_not_readable_or_rerunnable(client):
    """The record carries the whole design — coordinates, power, antenna.
    It must be no more readable than the raster it describes."""
    import time
    def account(tag):
        r = client.post("/api/auth/register", json={
            "email": f"{tag}{time.time_ns()}@x.io", "password": "hunter22secure",
            "role": "field", "org_name": ""})
        return {"Authorization": f"Bearer {r.json()['token']}"}

    mine, theirs = account("a"), account("b")
    cid = client.post("/api/rf/coverage", json=BODY,
                      headers=mine).json()["coverage_id"]

    assert client.get(f"/api/rf/coverage/{cid}/record",
                      headers=mine).status_code == 200
    # 404, not 403: an id must not become an existence oracle.
    assert client.get(f"/api/rf/coverage/{cid}/record",
                      headers=theirs).status_code == 404
    assert client.post(f"/api/rf/coverage/{cid}/rerun",
                       headers=theirs).status_code == 404


def test_a_study_predating_the_format_says_so_instead_of_inventing_one(client):
    """A record assembled after the fact from partial metadata would be a
    guess wearing the clothes of evidence."""
    from app.services import results_store
    cid = _run(client)["coverage_id"]
    png, meta = results_store.load("coverage", cid)
    meta.pop("record")
    results_store.save("coverage", cid, png, meta)

    r = client.get(f"/api/rf/coverage/{cid}/record")
    assert r.status_code == 404
    assert "re-run" in r.json()["detail"]
    assert client.post(f"/api/rf/coverage/{cid}/rerun").status_code == 404


def test_the_exported_pdf_carries_the_study_reference(client):
    """A picture with no reference is just a picture.

    Someone disputing this plot a year from now has to be able to quote
    something back and ask for the record — or for a re-run.
    """
    import base64
    import re
    import zlib

    cov = _run(client)
    pdf = client.post("/api/saas/report.pdf", json={
        "title": "Quarry coverage", "technology": "pmr446",
        "coverage_id": cov["coverage_id"], "include_costs": False})
    assert pdf.status_code == 200, pdf.text

    text = ""
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", pdf.content, re.S):
        raw = m.group(1).strip()
        try:
            raw = base64.a85decode(raw, adobe=True)
        except ValueError:
            pass
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        text += "".join(lit[1:-1].decode("latin-1")
                        for lit in re.findall(rb"\((?:[^()\\]|\\.)*\)", raw))

    assert cov["study_digest"] in text
    assert cov["coverage_id"] in text
