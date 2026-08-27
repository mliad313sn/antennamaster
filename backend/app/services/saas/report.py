"""Executive PDF report engine (ReportLab): branded, client-ready deliverable.

One call assembles: white-label header (uploaded logo or product mark),
study summary, link-budget matrix, terrain profile chart (rendered with PIL
so no browser is needed), coverage heatmap, equipment BOM with CAPEX/OPEX,
and a plain-language verdict - the document a pre-sales architect attaches
to a proposal.
"""
from __future__ import annotations

import io
import time

from PIL import Image, ImageDraw
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (Image as RLImage, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

from .pdf_text import esc

ACCENT = colors.HexColor("#2a78d6")
INK = colors.HexColor("#0b0b0b")
MUTED = colors.HexColor("#52514e")


def render_profile_chart(points: list[dict], width: int = 1000,
                         height: int = 320) -> bytes:
    """Terrain profile + LOS as a PNG via PIL (headless, fast)."""
    img = Image.new("RGB", (width, height), (252, 252, 251))
    draw = ImageDraw.Draw(img)
    if len(points) < 2:
        return _png(img)
    pad = 28
    xs = [p["d"] for p in points]
    terr = [p["elev_curved"] for p in points]
    los = [p["los"] for p in points]
    lo = min(min(terr), min(los))
    hi = max(max(terr), max(los))
    span = max(hi - lo, 1.0)

    def px(d: float, e: float) -> tuple[float, float]:
        x = pad + (d - xs[0]) / max(xs[-1] - xs[0], 1.0) * (width - 2 * pad)
        y = height - pad - (e - lo) / span * (height - 2 * pad)
        return x, y

    # Terrain fill, colored by provenance (blue srtm / orange dxf).
    base_y = height - pad
    poly_srtm, poly_dxf = [], []
    for p in points:
        (poly_dxf if p.get("dxf_weight", 0) >= 0.5 else poly_srtm).append(
            px(p["d"], p["elev_curved"]))
    for poly, fill in ((poly_srtm, (42, 120, 214)), (poly_dxf, (235, 104, 52))):
        if len(poly) >= 2:
            draw.polygon([(poly[0][0], base_y), *poly, (poly[-1][0], base_y)],
                         fill=tuple(int(c * 0.35 + 252 * 0.65) for c in fill))
            draw.line(poly, fill=fill, width=3)
    # Line of sight.
    draw.line([px(d, e) for d, e in zip(xs, los)], fill=(11, 11, 11), width=2)
    # Axes.
    draw.rectangle([pad, pad, width - pad, height - pad], outline=(195, 194, 183))
    return _png(img)


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def build_report(*, title: str, org_name: str, logo_png: bytes | None,
                 study: dict | None, profile_points: list[dict] | None,
                 rf: dict | None, distance_m: float | None,
                 coverage_png: bytes | None, coverage_stats: dict | None,
                 costs: dict | None, study_ref: dict | None = None) -> bytes:
    """Assemble the PDF; every section is optional and skipped when absent."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=16 * mm,
                            bottomMargin=14 * mm, leftMargin=16 * mm,
                            rightMargin=16 * mm, title=title)
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=INK, fontSize=20,
                        spaceAfter=2)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=ACCENT,
                        spaceBefore=10, spaceAfter=4)
    body = ParagraphStyle("body", parent=ss["Normal"], textColor=INK)
    muted = ParagraphStyle("muted", parent=ss["Normal"], textColor=MUTED,
                           fontSize=9)
    flow: list = []

    # ------------------------------------------------------------- header
    header_cells: list = []
    if logo_png:
        header_cells.append(RLImage(io.BytesIO(logo_png), width=34 * mm,
                                    height=14 * mm, kind="proportional"))
    # org_name and title are user text and land in a markup-parsing sink.
    header_cells.append(Paragraph(
        f"<b>{esc(org_name or 'AntennaMaster')}</b> — RF Coverage Study", muted))
    flow.append(Table([header_cells], colWidths=None,
                      style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")])))
    flow.append(Paragraph(esc(title), h1))
    flow.append(Paragraph(time.strftime("Generated %Y-%m-%d %H:%M UTC",
                                        time.gmtime()), muted))
    flow.append(Spacer(1, 6))

    # -------------------------------------------------------- link budget
    if study:
        flow.append(Paragraph("Link budget", h2))
        tech = study.get("technology", {})
        rows = [["Parameter", "Value"],
                ["Technology", tech.get("label", "-")],
                ["Frequency", f"{tech.get('freq_mhz', 0):,.0f} MHz"],
                ["Model", tech.get("model", "-")],
                ["TX power", f"{tech.get('tx_power_dbm', 0):.1f} dBm"],
                ["Antenna gains (TX / RX)",
                 f"{tech.get('tx_gain_dbi', 0):.1f} / {tech.get('rx_gain_dbi', 0):.1f} dBi"],
                ["Path loss", f"{study.get('path_loss_db', 0):.1f} dB"],
                ["Diffraction (Deygout)", f"{study.get('diffraction_loss_db', 0):.1f} dB"]]
        for key, label in (("foliage_loss_db", "Foliage (Weissberger)"),
                           ("rain_loss_db", "Rain (ITU-R P.838)"),
                           ("gaseous_loss_db", "Atmospheric gases"),
                           ("clutter_loss_db", "Clutter (ITU-R P.2108)")):
            if study.get(key):
                rows.append([label, f"{study[key]:.1f} dB"])
        if study.get("mimo_gain_db"):
            rows.append(["MIMO gain", f"+{study['mimo_gain_db']:.1f} dB"])
        rows += [["RX power", f"{study.get('rx_power_dbm', 0):.1f} dBm"],
                 ["Sensitivity", f"{study.get('sensitivity_dbm', tech.get('rx_sensitivity_dbm', 0)):.1f} dBm"],
                 ["Margin", f"{study.get('margin_db', 0):.1f} dB"],
                 ["Verdict", "SERVED" if study.get("served") else "NOT SERVED"]]
        flow.append(_table(rows))

    if rf and distance_m:
        flow.append(Paragraph("Path analysis", h2))
        flow.append(_table([
            ["Metric", "Value"],
            ["Distance", f"{distance_m / 1000:.2f} km"],
            ["Line of sight", "clear" if rf.get("line_of_sight_clear") else "obstructed"],
            ["Knife-edge loss", f"{rf.get('knife_edge_loss_db', 0):.1f} dB"],
            ["First Fresnel clearance", f"{rf.get('fresnel_clearance_ratio', 0) * 100:.0f}%"],
            ["k-factor", f"{rf.get('k_factor', 4 / 3):.2f}"],
        ]))

    # ------------------------------------------------------ profile chart
    if profile_points:
        flow.append(Paragraph("Terrain profile (k-curved, blue = SRTM, "
                              "orange = DXF)", h2))
        chart = render_profile_chart(profile_points)
        flow.append(RLImage(io.BytesIO(chart), width=178 * mm, height=57 * mm))

    # ---------------------------------------------------- coverage heatmap
    if coverage_png:
        flow.append(Paragraph("Coverage map", h2))
        img = ImageReader(io.BytesIO(coverage_png))
        iw, ih = img.getSize()
        w = 150 * mm
        flow.append(RLImage(io.BytesIO(coverage_png), width=w,
                            height=w * ih / iw))
        if coverage_stats:
            # Print only figures the engine actually produced.  A missing value
            # is omitted -- never defaulted to 0, which would render as a real
            # measurement ("Peak RX 0.0 dBm") on a signed document.
            served = coverage_stats.get("served_area_fraction")
            peak = coverage_stats.get("max_rx_power_dbm")
            parts = []
            if served is not None:
                parts.append(f"Served area: {served * 100:.0f}%")
            if peak is not None:
                parts.append(f"peak RX {peak:.1f} dBm")
            if parts:
                flow.append(Paragraph(" · ".join(parts), body))

    # ------------------------------------------------- equipment & budget
    if costs:
        flow.append(Paragraph("Equipment & budget estimate", h2))
        rows = [["Item", "Qty", "Unit (USD)", "Line (USD)"]]
        rows += [[i["item"], str(i["qty"]), f"{i['unit_usd']:,.0f}",
                  f"{i['line_usd']:,.0f}"] for i in costs["bom_per_site"]]
        rows += [["CAPEX per site", "", "", f"{costs['capex_per_site_usd']:,.0f}"],
                 [f"CAPEX total ({costs['sites']} site(s))", "", "",
                  f"{costs['capex_total_usd']:,.0f}"],
                 ["OPEX per year (fleet)", "", "",
                  f"{costs['opex_total_year_usd']:,.0f}"],
                 ["5-year TCO", "", "", f"{costs['tco_5y_usd']:,.0f}"]]
        flow.append(_table(rows, header_cols=4))
        flow.append(Paragraph("Indicative list prices for first-pass "
                              "budgeting; request vendor quotes for "
                              "procurement.", muted))

    # ------------------------------------------------- study of record
    if study_ref:
        flow.append(Spacer(1, 10))
        flow.append(Paragraph(
            f"Study of record {esc(study_ref['digest'])} · result "
            f"{esc(study_ref['coverage_id'])} · engine "
            f"{esc(study_ref.get('model') or '-')} · AntennaMaster "
            f"{esc(study_ref.get('app_version') or '-')}. The full input set "
            "and provenance behind this map are retrievable under that "
            "result id, and the study can be re-run on its recorded inputs.",
            muted))

    doc.build(flow)
    return buf.getvalue()


def _table(rows: list[list[str]], header_cols: int = 2) -> Table:
    t = Table(rows, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#e1e0d9")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.white, colors.HexColor("#f6f6f4")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t
