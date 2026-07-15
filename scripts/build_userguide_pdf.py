#!/usr/bin/env python3
"""Render a Markdown user guide into a professional, print-ready PDF.

A self-contained Markdown→ReportLab renderer tuned for the AntennaMaster user
guide: a branded cover page, coloured section headings, zebra-striped tables
with wrapped cells, monospace code blocks, running header/footer and
"Page X / Y" numbering. Uses DejaVu (full Unicode) so degree signs, subscripts,
math operators and French accents all render correctly.

    python build_userguide_pdf.py IN.md OUT.pdf "Title" "Subtitle" "Lang tag"
"""
from __future__ import annotations

import html
import re
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable,
                                ListFlowable, ListItem, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer,
                                Table, TableStyle)

# ---------------------------------------------------------------- branding
BRAND = colors.HexColor("#0d366b")      # deep blue (primary)
ACCENT = colors.HexColor("#2a78d6")     # link / accent blue
INK = colors.HexColor("#1a2230")
MUTED = colors.HexColor("#5b6675")
RULE = colors.HexColor("#c9d4e2")
ZEBRA = colors.HexColor("#f2f6fb")
CODEBG = colors.HexColor("#eef1f5")
THEAD = BRAND

DEJAVU = "/usr/share/fonts/truetype/dejavu"
LIB = "/usr/share/fonts/truetype/liberation"


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("Body", f"{DEJAVU}/DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("Body-Bold", f"{DEJAVU}/DejaVuSans-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("Body-Italic", f"{LIB}/LiberationSans-Italic.ttf"))
    pdfmetrics.registerFont(TTFont("Body-BoldItalic", f"{LIB}/LiberationSans-BoldItalic.ttf"))
    pdfmetrics.registerFont(TTFont("Mono", f"{DEJAVU}/DejaVuSansMono.ttf"))
    pdfmetrics.registerFont(TTFont("Mono-Bold", f"{DEJAVU}/DejaVuSansMono-Bold.ttf"))
    pdfmetrics.registerFontFamily("Body", normal="Body", bold="Body-Bold",
                                  italic="Body-Italic", boldItalic="Body-BoldItalic")


# ------------------------------------------------------------- inline markup
def inline(text: str) -> str:
    """Markdown inline → ReportLab mini-HTML (bold/italic/code/links)."""
    # Protect code spans first so their contents are not re-formatted.
    spans: list[str] = []

    def stash(m: re.Match) -> str:
        spans.append(m.group(1))
        return f"\x00{len(spans) - 1}\x00"

    text = re.sub(r"`([^`]+)`", stash, text)
    text = html.escape(text, quote=False)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*(?!\*)([^*\n]+?)\*(?!\*)", r"<i>\1</i>", text)
    # Links: [label](url) — http links stay clickable, anchors become plain text.
    def link(m: re.Match) -> str:
        label, url = m.group(1), m.group(2)
        if url.startswith("http"):
            return f'<link href="{url}" color="#2a78d6">{label}</link>'
        return label
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", link, text)

    def restore(m: re.Match) -> str:
        code = html.escape(spans[int(m.group(1))], quote=False)
        return f'<font face="Mono" size="8.5" backColor="#eef1f5"> {code} </font>'
    return re.sub(r"\x00(\d+)\x00", restore, text)


# --------------------------------------------------------------- styles
def styles() -> dict:
    ss = getSampleStyleSheet()
    S = {}
    S["body"] = ParagraphStyle("body", parent=ss["Normal"], fontName="Body",
                               fontSize=9.5, leading=14.5, textColor=INK,
                               alignment=TA_JUSTIFY, spaceAfter=6)
    S["h1"] = ParagraphStyle("h1", fontName="Body-Bold", fontSize=19, leading=23,
                             textColor=BRAND, spaceBefore=18, spaceAfter=6,
                             keepWithNext=1)
    S["h2"] = ParagraphStyle("h2", fontName="Body-Bold", fontSize=13.5, leading=17,
                             textColor=BRAND, spaceBefore=14, spaceAfter=4,
                             keepWithNext=1)
    S["h3"] = ParagraphStyle("h3", fontName="Body-Bold", fontSize=11, leading=15,
                             textColor=ACCENT, spaceBefore=10, spaceAfter=3,
                             keepWithNext=1)
    S["li"] = ParagraphStyle("li", parent=S["body"], spaceAfter=3, alignment=TA_LEFT)
    S["code"] = ParagraphStyle("code", fontName="Mono", fontSize=8.5, leading=12,
                               textColor=INK, leftIndent=8, spaceBefore=2, spaceAfter=2)
    S["cell"] = ParagraphStyle("cell", fontName="Body", fontSize=8.3, leading=11,
                               textColor=INK, alignment=TA_LEFT)
    S["cellh"] = ParagraphStyle("cellh", fontName="Body-Bold", fontSize=8.3,
                                leading=11, textColor=colors.white)
    S["cover_t"] = ParagraphStyle("cover_t", fontName="Body-Bold", fontSize=34,
                                  leading=40, textColor=BRAND)
    S["cover_s"] = ParagraphStyle("cover_s", fontName="Body", fontSize=15,
                                  leading=20, textColor=MUTED)
    S["cover_m"] = ParagraphStyle("cover_m", fontName="Body", fontSize=10,
                                  leading=15, textColor=MUTED)
    return S


# --------------------------------------------------------------- md → blocks
def parse_table(rows: list[str], S: dict) -> Table:
    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    header = cells(rows[0])
    body = [cells(r) for r in rows[2:]]
    ncols = len(header)
    fs = 6.6 if ncols >= 8 else (7.6 if ncols >= 6 else 8.3)
    ch = ParagraphStyle("ch", parent=S["cellh"], fontSize=fs, leading=fs + 2.5)
    cb = ParagraphStyle("cb", parent=S["cell"], fontSize=fs, leading=fs + 2.5)

    data = [[Paragraph(inline(c) or "&nbsp;", ch) for c in header]]
    for r in body:
        r = (r + [""] * ncols)[:ncols]
        data.append([Paragraph(inline(c) or "", cb) for c in r])

    avail = A4[0] - 4 * cm
    # Weight columns by their longest cell so wide columns get more room.
    widths = []
    for j in range(ncols):
        longest = max([len(header[j])] + [len(row[j]) if j < len(row) else 0 for row in body] + [1])
        widths.append(longest)
    total = sum(widths)
    colw = [max(1.3 * cm, avail * w / total) for w in widths]
    scale = avail / sum(colw)
    colw = [w * scale for w in colw]

    t = Table(data, colWidths=colw, repeatRows=1, hAlign="LEFT")
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), THEAD),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, BRAND),
        ("GRID", (0, 0), (-1, -1), 0.35, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for i in range(1, len(data)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), ZEBRA))
    t.setStyle(TableStyle(style))
    return t


def build_flowables(md: str, S: dict) -> list:
    lines = md.split("\n")
    flow: list = []
    i = 0
    n = len(lines)
    first_h1_seen = False

    def flush_para(buf: list[str]) -> None:
        if buf:
            flow.append(Paragraph(inline(" ".join(buf)), S["body"]))

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # fenced code block
        if stripped.startswith("```"):
            i += 1
            code: list[str] = []
            while i < n and not lines[i].strip().startswith("```"):
                code.append(lines[i]); i += 1
            i += 1
            box = [Paragraph(html.escape(c) or "&nbsp;", S["code"]) for c in code]
            tbl = Table([[box]], colWidths=[A4[0] - 4 * cm])
            tbl.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), CODEBG),
                ("BOX", (0, 0), (-1, -1), 0.4, RULE),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]))
            flow.append(Spacer(1, 3)); flow.append(tbl); flow.append(Spacer(1, 5))
            continue

        # table (header line followed by a |---| separator)
        if stripped.startswith("|") and i + 1 < n and re.match(r"^\|[\s:|-]+\|?$", lines[i + 1].strip()):
            tbl_rows = []
            while i < n and lines[i].strip().startswith("|"):
                tbl_rows.append(lines[i]); i += 1
            flow.append(Spacer(1, 2))
            flow.append(parse_table(tbl_rows, S))
            flow.append(Spacer(1, 6))
            continue

        # headings
        if stripped.startswith("### "):
            flow.append(Paragraph(inline(stripped[4:]), S["h3"])); i += 1; continue
        if stripped.startswith("## "):
            flow.append(Paragraph(inline(stripped[3:]), S["h2"])); i += 1; continue
        if stripped.startswith("# "):
            if not first_h1_seen:      # the document title lives on the cover
                first_h1_seen = True; i += 1; continue
            flow.append(Paragraph(inline(stripped[2:]), S["h1"])); i += 1; continue

        # horizontal rule
        if stripped in ("---", "***", "___"):
            flow.append(Spacer(1, 3))
            flow.append(HRFlowable(width="100%", thickness=0.5, color=RULE))
            flow.append(Spacer(1, 3)); i += 1; continue

        # a list item may soft-wrap onto following indented lines — fold them in.
        def item_text(prefix: str) -> str:
            nonlocal i
            txt = re.sub(prefix, "", lines[i]); i += 1
            while (i < n and lines[i].strip() != "" and lines[i][:1] in (" ", "\t")
                   and not re.match(r"^\s*([-*]|\d+\.) ", lines[i])):
                txt += " " + lines[i].strip(); i += 1
            return txt

        # bullet list
        if re.match(r"^[-*] ", line):
            items = []
            while i < n and re.match(r"^[-*] ", lines[i]):
                items.append(Paragraph(inline(item_text(r"^[-*] ")), S["li"]))
            flow.append(ListFlowable([ListItem(it, leftIndent=12) for it in items],
                                     bulletType="bullet", start="•",
                                     bulletColor=ACCENT, bulletFontSize=7,
                                     leftIndent=10))
            continue

        # ordered list
        if re.match(r"^\d+\. ", line):
            items = []
            while i < n and re.match(r"^\d+\. ", lines[i]):
                items.append(Paragraph(inline(item_text(r"^\d+\. ")), S["li"]))
            flow.append(ListFlowable([ListItem(it, leftIndent=14) for it in items],
                                     bulletType="1", bulletColor=BRAND,
                                     bulletFontName="Body-Bold", leftIndent=12))
            continue

        # blank line
        if stripped == "":
            i += 1; continue

        # paragraph (accumulate until a blank or a block starter)
        buf = []
        while i < n and lines[i].strip() != "" and not re.match(
                r"^(#{1,3} |```|\||\s*[-*] |\s*\d+\. |---$)", lines[i]):
            buf.append(lines[i].strip()); i += 1
        flush_para(buf)

    return flow


# ------------------------------------------------------- page furniture
class GuideDoc(BaseDocTemplate):
    def __init__(self, path, title, lang, **kw):
        super().__init__(path, pagesize=A4, topMargin=2.2 * cm,
                         bottomMargin=1.8 * cm, leftMargin=2 * cm,
                         rightMargin=2 * cm, title=title, **kw)
        self.doc_title = title
        self.lang = lang
        frame = Frame(self.leftMargin, self.bottomMargin,
                      self.width, self.height, id="main")
        self.addPageTemplates([
            PageTemplate(id="cover", frames=[frame], onPage=self._cover_bg),
            PageTemplate(id="body", frames=[frame], onPage=self._chrome),
        ])

    def _cover_bg(self, canvas, doc):
        canvas.saveState()
        canvas.setFillColor(BRAND)
        canvas.rect(0, A4[1] - 4.2 * cm, A4[0], 4.2 * cm, stroke=0, fill=1)
        canvas.setFillColor(ACCENT)
        canvas.rect(0, A4[1] - 4.35 * cm, A4[0], 0.15 * cm, stroke=0, fill=1)
        canvas.setFillColor(BRAND)
        canvas.rect(0, 0, A4[0], 1.0 * cm, stroke=0, fill=1)
        canvas.restoreState()

    def _chrome(self, canvas, doc):
        canvas.saveState()
        # header
        canvas.setFont("Body", 8)
        canvas.setFillColor(MUTED)
        canvas.drawString(2 * cm, A4[1] - 1.25 * cm, "AntennaMaster")
        canvas.drawRightString(A4[0] - 2 * cm, A4[1] - 1.25 * cm, self.doc_title)
        canvas.setStrokeColor(RULE); canvas.setLineWidth(0.4)
        canvas.line(2 * cm, A4[1] - 1.45 * cm, A4[0] - 2 * cm, A4[1] - 1.45 * cm)
        # footer
        canvas.setStrokeColor(RULE)
        canvas.line(2 * cm, 1.4 * cm, A4[0] - 2 * cm, 1.4 * cm)
        canvas.setFont("Body", 8); canvas.setFillColor(MUTED)
        strap = ("AntennaMaster — Simulateur de couverture RF" if self.lang == "fr"
                 else "AntennaMaster — RF Coverage Simulator")
        canvas.drawString(2 * cm, 1.0 * cm, strap)
        canvas.drawRightString(A4[0] - 2 * cm, 1.0 * cm,
                               f"Page {doc.page - 1} / {self._page_total}")
        canvas.restoreState()

    _page_total = 1


def build(md_path: str, out_path: str, title: str, subtitle: str, lang: str,
          meta_line: str) -> None:
    register_fonts()
    S = styles()
    with open(md_path, encoding="utf-8") as f:
        md = f.read()

    def make_story() -> list:
        st: list = [
            Spacer(1, 5.2 * cm),
            Paragraph(title, S["cover_t"]),
            Spacer(1, 0.3 * cm),
            Paragraph(subtitle, S["cover_s"]),
            Spacer(1, 0.6 * cm),
            HRFlowable(width="42%", thickness=2, color=ACCENT, hAlign="LEFT"),
            Spacer(1, 0.5 * cm),
            Paragraph(meta_line, S["cover_m"]),
            NextPageTemplate("body"),   # switch off the cover template
            PageBreak(),
        ]
        st += build_flowables(md, S)
        return st

    # Two-pass render so the footer can print "Page X / Y".
    import io
    probe = GuideDoc(io.BytesIO(), title=title, lang=lang)
    probe.build(make_story())
    doc = GuideDoc(out_path, title=title, lang=lang)
    doc._page_total = probe.page - 1
    doc.build(make_story())


if __name__ == "__main__":
    md_path, out_path, title, subtitle, lang, meta = sys.argv[1:7]
    build(md_path, out_path, title, subtitle, lang, meta)
    print(f"wrote {out_path}")
