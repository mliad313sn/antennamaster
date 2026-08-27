"""The branded PDF must actually come out.

`ReportRequest` deliberately rejects unknown keys, and deliberately removed
`served_area_fraction` / `max_rx_power_dbm` rather than deprecating them: the
figures printed in a signed document are read from the STORED study, because a
headline number supplied by the client is a fabrication vector. That reasoning
is right and its docstring says so.

What it did not survive was the client. The pitch screen — whose own intro
says "then export the branded PDF" — kept sending both removed fields, so
every Executive PDF export answered 422 and the button did nothing but write a
validation message into the error box. Measured in the browser: 0 of 4
attempts produced a file, on a basic account and on an enterprise one alike.

So this pins both halves of the contract at once: the exact body the screen
sends must produce a PDF, and the removed fields must still be refused.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _account(client):
    r = client.post("/api/auth/register", json={
        "email": f"rep{time.time_ns()}@x.io", "password": "hunter22secure",
        "organization": "Report Co"})
    assert r.status_code == 200, r.text
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    client.post("/api/auth/tier", json={"tier": "enterprise"}, headers=h)
    return h


def _study(client, headers):
    r = client.post("/api/rf/coverage", json={
        "lat": 47.05, "lon": 15.45, "technology": "gsm900", "radius_km": 3,
        "n_radials": 36, "n_steps": 20}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["png_url"].split("/")[-1].replace(".png", "")


def test_the_body_the_pitch_screen_sends_produces_a_pdf(client):
    headers = _account(client)
    cid = _study(client, headers)
    r = client.post("/api/saas/report.pdf", json={
        "title": "Option A — gsm900 @ 47.05, 15.45",
        "technology": "gsm900", "sites": 3, "coverage_id": cid,
    }, headers=headers)
    assert r.status_code == 200, r.text
    assert r.content[:5] == b"%PDF-", "not a PDF"
    assert len(r.content) > 1000, f"suspiciously small: {len(r.content)} bytes"


def test_client_supplied_headline_figures_are_still_refused(client):
    """The hardening must not be loosened to make the export work: the fix
    belongs on the client, which should not have been sending these."""
    headers = _account(client)
    cid = _study(client, headers)
    r = client.post("/api/saas/report.pdf", json={
        "title": "Fabricated", "technology": "gsm900", "sites": 1,
        "coverage_id": cid,
        "served_area_fraction": 0.99,      # a number the client made up
        "max_rx_power_dbm": -20.0,
    }, headers=headers)
    assert r.status_code == 422, (
        "a signed report accepted a headline figure from the request body")
    locs = {tuple(e["loc"]) for e in r.json()["detail"]}
    assert ("body", "served_area_fraction") in locs
    assert ("body", "max_rx_power_dbm") in locs
