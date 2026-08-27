"""Ready-to-file EMF compliance dossier (PDF).

Turns the C-phase EMF engine (ICNIRP / FCC OET-65 exclusion zones) into the
document a permitting authority actually receives: site identification, the
applicable standard and limits, a per-antenna assessment table (EIRP, public
and occupational compliance distances), the governing method, and signature
blocks. The tool produces the dossier *in the expected format*; the legal
sign-off remains the submitting engineer's — stated plainly on the document.
"""
from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from ..rf.compliance import assess_exposure
from .pdf_text import esc

BRAND = colors.HexColor("#0d366b")
MUTED = colors.HexColor("#5b6675")
RULE = colors.HexColor("#c9d4e2")

_TITLE = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=18,
                        leading=22, textColor=BRAND, spaceAfter=4)
_H2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12,
                     leading=15, textColor=BRAND, spaceBefore=12, spaceAfter=4)
_BODY = ParagraphStyle("b", fontName="Helvetica", fontSize=9.5, leading=13.5)
_SMALL = ParagraphStyle("s", fontName="Helvetica", fontSize=8, leading=11,
                        textColor=MUTED)


def _kv_table(rows: list[tuple[str, str]]) -> Table:
    # Values are user text (site name, operator, notes): escaped, or the
    # Paragraph parser eats "<north>" out of a mast name and honours a
    # "<font color=white>" someone typed into it.
    t = Table([[Paragraph(f"<b>{esc(k)}</b>", _BODY), Paragraph(esc(v), _BODY)]
               for k, v in rows], colWidths=[4.5 * cm, 11.5 * cm])
    t.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.3, RULE),
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f2f6fb")),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t


def build_emf_report(site: dict, antennas: list[dict], standard: str = "icnirp",
                     ground_reflection: bool = True) -> bytes:
    """Render the EMF dossier; returns PDF bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=1.8 * cm,
                            bottomMargin=1.8 * cm, leftMargin=2 * cm,
                            rightMargin=2 * cm,
                            title="EMF compliance assessment")
    story: list = []
    std_label = ("ICNIRP 2020 general public / occupational reference levels"
                 if standard.lower() == "icnirp"
                 else "FCC OET Bulletin 65 MPE limits")

    story.append(Paragraph("RF Exposure (EMF) Compliance Assessment", _TITLE))
    story.append(Paragraph(f"Standard applied: <b>{std_label}</b> — "
                           f"far-field power-density method, "
                           f"{'with' if ground_reflection else 'without'} "
                           f"ground-reflection worst case", _BODY))
    story.append(Spacer(1, 8))
    story.append(HRFlowable(width="100%", thickness=0.7, color=BRAND))

    story.append(Paragraph("1. Site identification", _H2))
    story.append(_kv_table([
        ("Site name", str(site.get("name", "—"))),
        ("Operator", str(site.get("operator", "—"))),
        ("Coordinates", f"{site.get('lat', '—')}, {site.get('lon', '—')}"),
        ("Assessment date", date.today().isoformat()),
        ("Notes", str(site.get("notes", "—"))),
    ]))

    story.append(Paragraph("2. Per-antenna assessment", _H2))
    head = ["Antenna", "MHz", "TX dBm", "Gain dBi", "EIRP dBm",
            "Public limit W/m²", "Public excl. m", "Occup. excl. m"]
    rows = [head]
    results = []
    for a in antennas:
        r = assess_exposure(float(a["freq_mhz"]), float(a["tx_power_dbm"]),
                            float(a["antenna_gain_dbi"]),
                            losses_db=float(a.get("losses_db", 0.0)),
                            ground_reflection=ground_reflection,
                            standard=standard)
        results.append(r)
        rows.append([str(a.get("label", "—")), f"{a['freq_mhz']:g}",
                     f"{a['tx_power_dbm']:g}", f"{a['antenna_gain_dbi']:g}",
                     f"{r['eirp_dbm']:.1f}", f"{r['public_limit_w_m2']:g}",
                     f"{r['public_compliance_distance_m']:.2f}",
                     f"{r['occupational_compliance_distance_m']:.2f}"])
    t = Table(rows, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.3, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    story.append(t)

    worst_pub = max(r["public_compliance_distance_m"] for r in results)
    worst_occ = max(r["occupational_compliance_distance_m"] for r in results)
    story.append(Paragraph("3. Exclusion-zone summary", _H2))
    story.append(_kv_table([
        ("Public (uncontrolled) exclusion distance",
         f"{worst_pub:.2f} m (largest across all antennas)"),
        ("Occupational (controlled) exclusion distance",
         f"{worst_occ:.2f} m (largest across all antennas)"),
        ("Method", "Far-field S = EIRP/(4πr²)"
                   + (" × 1.6 ground-reflection factor (OET-65 worst case)"
                      if ground_reflection else "")),
    ]))

    story.append(Paragraph("4. Method statement & declarations", _H2))
    story.append(Paragraph(
        "Compliance distances are computed with the far-field power-density "
        "method against the frequency-dependent reference levels of the "
        f"selected standard ({std_label}). Simultaneous-exposure summation "
        "across co-located emitters, near-field effects within the antenna "
        "aperture, and site-specific access restrictions must be reviewed by "
        "the signing engineer. This document is generated by AntennaMaster; "
        "the legal responsibility for the filing rests with the undersigned.",
        _BODY))
    story.append(Spacer(1, 22))
    sig = Table([[Paragraph("Prepared by (engineer):", _SMALL),
                  Paragraph("Reviewed / approved:", _SMALL)],
                 [Paragraph("<br/><br/>Signature: ______________________",
                            _SMALL),
                  Paragraph("<br/><br/>Signature: ______________________",
                            _SMALL)]],
                colWidths=[8 * cm, 8 * cm])
    story.append(sig)

    doc.build(story)
    return buf.getvalue()
