"""An indoor heatmap id must not be a bearer capability either.

Outdoor coverage was hardened against this — `resolve_result` exists because
a 12-hex result id travels in share links, exported PDF footers, audit detail
fields and reverse-proxy logs, so treating knowledge of one as authorisation
leaked other tenants' georeferenced site footprints. The indoor studio, which
writes to the same `results_store`, was left behind: `/api/indoor/coverage/
{id}.png` took no user dependency at all.

What that exposes is not a colour ramp. It is a building's interior, drawn to
scale from the customer's own uploaded floor plan, with the wall materials and
the antenna placement that were studied — for a hospital, a prison, a mine
gallery or a public-safety site. That is the same class of confidential
information the outdoor fix protects, and arguably a more sensitive one.

Mirrors `test_coverage_results_are_owner_scoped`, including the two properties
that make it a real fix rather than a nominal one: a non-owner gets 404 rather
than 403 (so the id is not an existence oracle), and an anonymous
self-hosted deployment — where results have no owner — keeps working.
"""
import time

import pytest
from fastapi.testclient import TestClient

import app.api.routes_terrain as routes_terrain
import app.services.terrain.fusion as fusion_mod
from app.main import app
from app.services.terrain.fusion import TerrainFusionService


@pytest.fixture
def client(fake_store, monkeypatch):
    monkeypatch.setattr(fusion_mod, "get_tile_store", lambda: fake_store)
    monkeypatch.setattr(routes_terrain, "_fusion",
                        TerrainFusionService(store=fake_store))
    return TestClient(app)


def _register(client, email):
    r = client.post("/api/auth/register", json={
        "email": email, "password": "hunter22secure"})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    # The indoor studio is a Pro capability; a basic account is refused 402
    # before ownership is ever reached.
    client.post("/api/auth/tier", json={"tier": "pro"}, headers=headers)
    return headers


def _floorplan_study(client, site_dxf, headers=None):
    """Upload the synthetic survey DXF and run one indoor study on it."""
    with open(site_dxf, "rb") as fh:
        up = client.post("/api/dxf/upload", files={"file": ("site.dxf", fh)},
                         **({"headers": headers} if headers else {}))
    assert up.status_code == 200, up.text
    dxf_id = up.json()["dxf_id"]
    body = {"dxf_id": dxf_id, "layer_materials": {"BUILDINGS": "brick"},
            "tx_x": 15.0, "tx_y": 15.0, "technology": "wifi2400",
            "grid_px": 60}
    r = client.post("/api/indoor/coverage", json=body,
                    **({"headers": headers} if headers else {}))
    assert r.status_code == 200, r.text
    return r.json()["png_url"]


def test_an_indoor_heatmap_does_not_leak_to_another_account(client, site_dxf):
    owner = _register(client, f"indoor{time.time_ns()}@x.io")
    url = _floorplan_study(client, site_dxf, owner)

    assert client.get(url, headers=owner).status_code == 200, (
        "the owner cannot read their own floor-plan study")

    stranger = _register(client, f"other{time.time_ns()}@x.io")
    for headers in (stranger, None):
        r = client.get(url, headers=headers) if headers else client.get(url)
        assert r.status_code == 404, (
            "a floor plan leaked to someone holding only the result id")


def test_anonymous_indoor_studies_stay_open_for_self_hosting(client, site_dxf):
    """Owner-scoping must not break the single-tenant install: a result with
    no owner stays readable, exactly like an anonymous DXF or coverage."""
    url = _floorplan_study(client, site_dxf)
    assert client.get(url).status_code == 200


def test_an_owned_heatmap_is_not_offered_to_shared_caches(client, site_dxf):
    """`private`, so a reverse proxy or CDN cannot hand one tenant's floor
    plan to the next requester for that URL. RFC 9111 already stops a
    compliant shared cache from storing a response to an authorised request,
    but that protection rests on every intermediary implementing it; saying
    so costs nothing and does not stop the user's own browser caching it."""
    owner = _register(client, f"cache{time.time_ns()}@x.io")
    url = _floorplan_study(client, site_dxf, owner)
    cc = client.get(url, headers=owner).headers["cache-control"]
    assert "private" in cc, f"an owned heatmap advertised {cc!r} to any cache"

    # An anonymous result belongs to nobody and stays shareable.
    anon = _floorplan_study(client, site_dxf)
    assert "private" not in client.get(anon).headers["cache-control"]
