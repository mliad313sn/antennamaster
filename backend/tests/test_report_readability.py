"""The exported report is signed by people who cannot read dB.

It goes to a mine manager, a municipality, a client's procurement lead — and
it opened straight into a link-budget table. Those readers cannot tell a 14 dB
margin from a 4 dB one, which is the entire question the document exists to
answer, so the answer now comes first, in words.

The risk that comes with a summary is that it drifts from the numbers below
it. Every sentence here is derived from the same figures the tables print,
and a missing figure produces no sentence rather than one built on a zero.
"""
import base64
import re
import zlib

import pytest

from app.services.saas.report import build_report, plain_summary


def _text(pdf: bytes) -> str:
    out = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", pdf, re.S):
        raw = m.group(1).strip()
        try:
            raw = base64.a85decode(raw, adobe=True)
        except ValueError:
            pass
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass
        out += [lit[1:-1].decode("latin-1")
                for lit in re.findall(rb"\((?:[^()\\]|\\.)*\)", raw)]
    return "".join(out)


@pytest.mark.parametrize("margin,expect", [
    (22.0, "comfortably"),
    (9.0, "closes"),
    (3.0, "only just"),      # closes on paper, fails in rain
    (-6.0, "does not close"),
])
def test_the_verdict_is_a_sentence_not_a_number(margin, expect):
    served = margin >= 0
    lines = plain_summary({"margin_db": margin, "served": served},
                          None, 8200.0, None)
    assert expect in lines[0]
    assert f"{abs(margin):.0f} dB" in lines[0]


def test_a_link_that_closes_by_3_db_is_not_described_as_working():
    """The dangerous case: positive margin, so every table says SERVED, and
    the link drops in the first heavy rain. A summary that called that
    "works" would be technically true and practically a lie."""
    thin = plain_summary({"margin_db": 3.0, "served": True}, None, 5000.0, None)[0]
    assert "only just" in thin
    assert "rain" in thin

    fine = plain_summary({"margin_db": 20.0, "served": True}, None, 5000.0, None)[0]
    assert "only just" not in fine


def test_no_figure_produces_no_sentence_rather_than_a_zero():
    assert plain_summary(None, None, None, None) == []
    # A study with no margin computed must not become "0 dB of headroom".
    assert plain_summary({"served": True}, None, 1000.0, None) == []


def test_coverage_is_reported_as_area_covered_not_a_fraction():
    lines = plain_summary(None, None, None, {"served_area_fraction": 0.83})
    joined = " ".join(lines)
    assert "83% is covered" in joined
    assert "most of the area" in joined
    # ...and it says what the colours mean, since that is the map's whole
    # point and no legend entry explains it.
    assert "headroom" in joined


def test_the_summary_always_says_it_is_a_prediction():
    """A signed document that reads as measurement when it is prediction is
    the single most expensive thing this report could get wrong."""
    lines = plain_summary({"margin_db": 12.0, "served": True}, None, 3000.0, None)
    assert any("not a measurement" in line for line in lines)


def test_the_summary_leads_the_document(monkeypatch):
    pdf = build_report(
        title="Quarry link", org_name="ACME", logo_png=None,
        study={"margin_db": 12.4, "served": True, "path_loss_db": 128.0,
               "rx_power_dbm": -85.0, "technology": {"label": "PMR446",
                                                     "freq_mhz": 446.1,
                                                     "model": "okumura_hata"}},
        profile_points=None,
        rf={"line_of_sight_clear": False, "k_factor": 1.33},
        distance_m=8200.0, coverage_png=None,
        coverage_stats={"served_area_fraction": 0.83}, costs=None)
    text = _text(pdf)

    assert "Summary" in text
    assert "Link budget" in text
    # The words come before the dB, not after them.
    assert text.index("Summary") < text.index("Link budget")
    assert "12 dB of headroom" in text
    assert "83% is covered" in text
    # An obstructed path is explained rather than left as a boolean.
    assert "bend over it" in text
