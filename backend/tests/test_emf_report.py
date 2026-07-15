"""Tests: ready-to-file EMF compliance dossier (C9)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.saas.compliance_report import build_emf_report

client = TestClient(app)

SITE = {"name": "Mine Nord — Puits 3", "operator": "ACME Mining",
        "lat": 47.05, "lon": 15.44, "notes": "rooftop, restricted access"}
ANTENNAS = [
    {"label": "GSM900 sector A", "freq_mhz": 945.0, "tx_power_dbm": 43.0,
     "antenna_gain_dbi": 15.0, "losses_db": 3.0},
    {"label": "LTE1800 sector A", "freq_mhz": 1842.0, "tx_power_dbm": 46.0,
     "antenna_gain_dbi": 17.0, "losses_db": 3.0},
]


def _text(pdf: bytes) -> str:
    import fitz
    doc = fitz.open(stream=pdf, filetype="pdf")
    return "".join(p.get_text() for p in doc)


def test_emf_report_builds_and_contains_assessment():
    pdf = build_emf_report(SITE, ANTENNAS, standard="icnirp",
                           ground_reflection=True)
    assert pdf[:5] == b"%PDF-"
    text = _text(pdf)
    assert "Mine Nord" in text and "ACME Mining" in text
    assert "ICNIRP" in text
    assert "GSM900 sector A" in text and "LTE1800 sector A" in text
    assert "Exclusion-zone summary" in text
    assert "Signature" in text          # sign-off stays with the engineer
    # The worst-case public distance must reflect the stronger antenna.
    from app.services.rf.compliance import assess_exposure
    strongest = max(
        assess_exposure(a["freq_mhz"], a["tx_power_dbm"],
                        a["antenna_gain_dbi"], losses_db=a["losses_db"],
                        ground_reflection=True)["public_compliance_distance_m"]
        for a in ANTENNAS)
    assert f"{strongest:.2f}" in text


def test_emf_report_fcc_variant():
    pdf = build_emf_report(SITE, ANTENNAS, standard="fcc",
                           ground_reflection=False)
    text = _text(pdf)
    assert "OET" in text
    assert "without ground-reflection" in text.replace("\n", " ")


def test_emf_report_api():
    r = client.post("/api/rf/compliance/report.pdf", json={
        "site": SITE, "antennas": ANTENNAS, "standard": "icnirp"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    bad = client.post("/api/rf/compliance/report.pdf", json={
        "site": SITE, "antennas": ANTENNAS, "standard": "gost"})
    assert bad.status_code == 422
