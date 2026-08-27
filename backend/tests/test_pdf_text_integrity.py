"""User text on a signed PDF must render as text, not as markup.

A ReportLab Paragraph parses a small HTML dialect, so every user value
interpolated into one is markup. On documents that get signed and filed —
an EMF compliance assessment, a client-facing coverage study — that has two
consequences: ordinary names silently lose characters, and the *input* can
restyle the document.
"""
import base64
import re
import zlib

from app.services.saas.compliance_report import build_emf_report
from app.services.saas.pdf_text import esc
from app.services.saas.report import build_report

ANTENNAS = [{"label": "Sector A", "freq_mhz": 900.0, "tx_power_dbm": 43.0,
             "antenna_gain_dbi": 17.0}]


def pdf_text(pdf: bytes) -> str:
    """The visible text of a PDF, as one string.

    ReportLab writes ASCII85 + Flate streams and splits a line into several
    show-text operands for kerning, so `Site <A>` arrives as `(Site <)(A)(>)`.
    Decoding the streams and concatenating the string literals is what makes
    an assertion about what the reader actually sees possible.
    """
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
        for lit in re.findall(rb"\((?:[^()\\]|\\.)*\)", raw):
            out.append(lit[1:-1].decode("latin-1"))
    return "".join(out)


def test_a_mast_name_with_angle_brackets_survives_onto_the_dossier():
    """`Mast A & B <north>` used to render as `Mast A & B` — the parser ate
    `<north>` as an unknown tag. A compliance filing that names the wrong
    structure is worse than one that fails to generate."""
    pdf = build_emf_report({"name": "Mast A & B <north>", "operator": "Op",
                            "lat": 47.0, "lon": 15.0, "notes": ""}, ANTENNAS)
    body = pdf_text(pdf)
    assert "north" in body, "the site name was silently truncated"
    assert "Mast A & B <north>" in body


def test_markup_typed_into_a_site_name_is_printed_not_obeyed():
    """The document states a compliance distance to a regulator. Letting the
    input restyle it — hide text in white, bold a verdict, pull in an image —
    is an integrity problem, not a cosmetic one."""
    hostile = '<font color="white">NOT ASSESSED</font><b>Compliant</b>'
    pdf = build_emf_report({"name": hostile, "operator": "Op", "lat": 47.0,
                            "lon": 15.0, "notes": ""}, ANTENNAS)
    body = pdf_text(pdf)
    # The tag is shown as characters the reader can see, and the text it
    # tried to style is not separated from it.
    assert '<font color="white">' in body
    assert "NOT ASSESSED" in body and "<b>Compliant</b>" in body


def test_free_text_notes_and_operator_are_escaped_too():
    pdf = build_emf_report({"name": "M1", "operator": "A & B <Ltd>",
                            "lat": 47.0, "lon": 15.0,
                            "notes": "roof <2m> clearance & fence"}, ANTENNAS)
    body = pdf_text(pdf)
    assert "A & B <Ltd>" in body
    assert "roof <2m> clearance & fence" in body


def test_the_coverage_report_header_and_title_are_escaped():
    """The org name is printed on every report header and the title is
    whatever the user typed — both went into a Paragraph raw."""
    pdf = build_report(title="Site <A> & <B> study",
                       org_name="Acme <Mining> & Co", logo_png=None,
                       study=None, profile_points=None, rf=None,
                       distance_m=None, coverage_png=None,
                       coverage_stats=None, costs=None)
    body = pdf_text(pdf)
    assert "Acme <Mining> & Co" in body
    assert "Site <A> & <B> study" in body


def test_esc_leaves_ordinary_text_alone():
    assert esc("Mast 12 - north") == "Mast 12 - north"
    assert esc("A & B") == "A &amp; B"
    assert esc(None) == "None"
