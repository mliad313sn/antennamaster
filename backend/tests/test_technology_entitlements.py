"""The preset list must say which presets the caller can actually run.

Four of them are gated — PtP backhaul (Pro) and the three private LTE/5G
presets (Enterprise) — and `/api/rf/technologies` returned no hint of it. The
interface therefore offered every preset identically and the only way to
discover the boundary was to run a study and be refused 402.

That is not a hypothetical. The pitch screen — the one built for showing a
customer — defaults Option A to `private_lte_b48`, so a new basic account's
very first action there failed with "The 'private_networks' capability
requires the enterprise plan". The dropdown was full of presets that account
could run; it just had no way to know which.

A boundary the user can see before they hit it is both a better experience and
a better upsell than an error message after the fact.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _register(client, email, tier=None):
    r = client.post("/api/auth/register",
                    json={"email": email, "password": "hunter22secure"})
    assert r.status_code == 200, r.text
    headers = {"Authorization": f"Bearer {r.json()['token']}"}
    if tier:
        client.post("/api/auth/tier", json={"tier": tier}, headers=headers)
    return headers


def _by_key(client, headers=None):
    r = client.get("/api/rf/technologies",
                   **({"headers": headers} if headers else {}))
    assert r.status_code == 200, r.text
    return {t["key"]: t for t in r.json()["technologies"]}


def test_every_preset_declares_the_plan_it_needs(client):
    techs = _by_key(client)
    assert techs, "no presets at all"
    for key, t in techs.items():
        assert "requires_plan" in t and "available" in t, key
    # The four the gate actually knows about, and nothing else.
    gated = {k: t["requires_plan"] for k, t in techs.items()
             if t["requires_plan"] is not None}
    assert gated == {"ptp18000": "pro",
                     "private_lte_b48": "enterprise",
                     "private_nr_n77": "enterprise",
                     "private_lte_iot": "enterprise"}, gated


def test_availability_follows_the_caller_s_plan(client):
    basic = _register(client, f"basic{time.time_ns()}@x.io")
    pro = _register(client, f"pro{time.time_ns()}@x.io", "pro")
    ent = _register(client, f"ent{time.time_ns()}@x.io", "enterprise")

    assert _by_key(client, basic)["private_lte_b48"]["available"] is False
    assert _by_key(client, basic)["ptp18000"]["available"] is False
    assert _by_key(client, pro)["ptp18000"]["available"] is True
    assert _by_key(client, pro)["private_lte_b48"]["available"] is False
    assert _by_key(client, ent)["private_lte_b48"]["available"] is True

    # An ungated preset is available to everyone, including a basic account.
    for headers in (basic, pro, ent):
        assert _by_key(client, headers)["pmr446"]["available"] is True


def test_it_agrees_with_the_gate_that_enforces_it(client):
    """The flag would be worse than nothing if it disagreed with reality: a
    preset marked available that then answers 402 is a promise broken one
    click later."""
    headers = _register(client, f"agree{time.time_ns()}@x.io", "pro")
    techs = _by_key(client, headers)
    for key in ("pmr446", "ptp18000", "private_lte_b48"):
        r = client.post("/api/rf/coverage", json={
            "lat": 47.0, "lon": 15.0, "technology": key, "radius_km": 2,
            "n_radials": 36, "n_steps": 20}, headers=headers)
        refused = r.status_code == 402
        assert techs[key]["available"] is not refused, (
            f"{key}: listed available={techs[key]['available']} but the study "
            f"answered {r.status_code}")


def test_anonymous_self_hosting_sees_everything_available(client):
    """With no account and no SaaS mode the gate lets everything through, and
    the list must say the same rather than showing locks that do not apply."""
    techs = _by_key(client)
    assert all(t["available"] for t in techs.values())
