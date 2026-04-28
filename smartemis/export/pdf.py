"""Branded PDF report exporter.

Takes a saved Report (with its KPI payload) + peer benchmarks and produces a
multi-page A4 PDF that mirrors the Smartemis consulting deliverable format:
  - Cover page: title, clinic, period, generated date
  - KPI tiles
  - Charts (revenue trend, mix, species, vets, top groups, payment status)
  - Executive narrative (the LLM-drafted text)
  - Recommendations section parsed from the narrative
  - Technical KPI appendix

The narrative parsing is best-effort — we look for the section headers our
system prompt asked Claude to use. If parsing fails, the full text falls back
into a single "Consulting analysis" block.
"""
from __future__ import annotations

import io
import re
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from . import charts

# Brand palette mirrored from charts.py
BRAND_BLUE = colors.HexColor("#1e3a8a")
BRAND_ACCENT = colors.HexColor("#0ea5e9")
BRAND_TEAL = colors.HexColor("#0d9488")
BRAND_GREY = colors.HexColor("#475569")
BRAND_LIGHT = colors.HexColor("#f1f5f9")
BRAND_BORDER = colors.HexColor("#cbd5e1")
TRAFFIC_GREEN = colors.HexColor("#16a34a")
TRAFFIC_AMBER = colors.HexColor("#d97706")
TRAFFIC_RED = colors.HexColor("#dc2626")

# Section headers our system prompt asks the LLM to produce — used for parsing
SECTION_HEADERS = [
    "EXECUTIVE SUMMARY",
    "REVENUE PERFORMANCE",
    "PRICING & GOT FACTOR ANALYSIS",
    "PRICING AND GOT FACTOR ANALYSIS",
    "CASE & SPECIES MIX",
    "CASE AND SPECIES MIX",
    "VET PRODUCTIVITY",
    "PAYMENT & COLLECTIONS",
    "PAYMENT AND COLLECTIONS",
    "RECOMMENDATIONS",
]


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "smTitle", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=26, leading=30, textColor=BRAND_BLUE, alignment=TA_LEFT,
        ),
        "subtitle": ParagraphStyle(
            "smSubtitle", parent=base["Normal"], fontName="Helvetica",
            fontSize=13, leading=16, textColor=BRAND_GREY, alignment=TA_LEFT,
        ),
        "h1": ParagraphStyle(
            "smH1", parent=base["Heading1"], fontName="Helvetica-Bold",
            fontSize=15, leading=20, textColor=BRAND_BLUE, spaceBefore=14, spaceAfter=8,
        ),
        "h2": ParagraphStyle(
            "smH2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=12, leading=15, textColor=BRAND_TEAL, spaceBefore=10, spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "smBody", parent=base["BodyText"], fontName="Helvetica",
            fontSize=10, leading=14, textColor=colors.HexColor("#1e293b"),
            alignment=TA_LEFT, spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "smBullet", parent=base["BodyText"], fontName="Helvetica",
            fontSize=10, leading=14, textColor=colors.HexColor("#1e293b"),
            leftIndent=14, bulletIndent=4, spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "smSmall", parent=base["BodyText"], fontName="Helvetica",
            fontSize=8, leading=11, textColor=BRAND_GREY,
        ),
        "tile_label": ParagraphStyle(
            "smTileLabel", parent=base["Normal"], fontName="Helvetica",
            fontSize=8, leading=10, textColor=BRAND_GREY, alignment=TA_CENTER,
        ),
        "tile_value": ParagraphStyle(
            "smTileValue", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=16, leading=20, textColor=BRAND_BLUE, alignment=TA_CENTER,
        ),
        "cover_label": ParagraphStyle(
            "smCoverLabel", parent=base["Normal"], fontName="Helvetica",
            fontSize=9, leading=12, textColor=BRAND_GREY,
        ),
        "cover_value": ParagraphStyle(
            "smCoverValue", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=12, leading=14, textColor=BRAND_BLUE,
        ),
    }


def _eur(v: float) -> str:
    return f"{v:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _embed_chart(png: bytes | None, *, width_cm: float = 16.0, max_h_cm: float = 12.0) -> Image | None:
    if not png:
        return None
    iw, ih = ImageReader(io.BytesIO(png)).getSize()
    aspect = ih / iw if iw else 0.5
    width_pt = width_cm * cm
    height_pt = min(width_pt * aspect, max_h_cm * cm)
    return Image(io.BytesIO(png), width=width_pt, height=height_pt)


def _kpi_tiles(kpis: dict[str, Any], styles: dict[str, ParagraphStyle]) -> Table:
    tiles = [
        ("Total revenue (net)", _eur(kpis.get("total_revenue_net", 0.0))),
        ("Invoices", f"{kpis.get('invoice_count', 0):,}".replace(",", ".")),
        ("Avg invoice", _eur(kpis.get("avg_invoice_value", 0.0))),
        ("Paid", _pct(kpis.get("pct_paid", 0.0))),
    ]
    cells = [
        [
            [Paragraph(label, styles["tile_label"]), Spacer(1, 4),
             Paragraph(value, styles["tile_value"])]
            for label, value in tiles
        ]
    ]
    t = Table(cells, colWidths=[4.0 * cm] * 4, rowHeights=[2.4 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, BRAND_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BRAND_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _peer_compare_table(kpis: dict[str, Any], peers: dict[str, Any],
                        styles: dict[str, ParagraphStyle]) -> Table:
    rows = [["Metric", "This clinic", "Network median", "Verdict"]]

    def verdict(this: float, peer: float, *, higher_better: bool) -> str:
        if peer == 0:
            return "n/a"
        diff = (this - peer) / peer
        if higher_better:
            if diff > 0.10: return "above peer"
            if diff < -0.10: return "below peer"
        else:
            if diff < -0.10: return "above peer"
            if diff > 0.10: return "below peer"
        return "in line"

    rows.append([
        "Total revenue (net)",
        _eur(kpis.get("total_revenue_net", 0.0)),
        _eur(peers.get("median_revenue", 0.0)),
        verdict(kpis.get("total_revenue_net", 0.0), peers.get("median_revenue", 0.0), higher_better=True),
    ])
    if kpis.get("avg_got_factor") is not None and peers.get("median_avg_factor"):
        rows.append([
            "Avg GOT factor",
            f"{kpis['avg_got_factor']:.2f}×",
            f"{peers['median_avg_factor']:.2f}×",
            verdict(kpis["avg_got_factor"], peers["median_avg_factor"], higher_better=True),
        ])
    rows.append([
        "% paid",
        _pct(kpis.get("pct_paid", 0.0)),
        _pct(peers.get("median_pct_paid", 0.0)),
        verdict(kpis.get("pct_paid", 0.0), peers.get("median_pct_paid", 0.0), higher_better=True),
    ])

    t = Table(rows, colWidths=[5.5 * cm, 4 * cm, 4 * cm, 3 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "CENTER"),
        ("BACKGROUND", (0, 1), (-1, -1), BRAND_LIGHT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, BRAND_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def _vet_table(vets: list[dict[str, Any]]) -> Table:
    rows = [["Vet ID", "Revenue", "Invoices", "€/Invoice", "Lineitems"]]
    for v in vets[:8]:
        rows.append([
            v["vet_id"][:22],
            _eur(v["revenue"]),
            f"{v['invoices']:,}".replace(",", "."),
            _eur(v["revenue_per_invoice"]),
            f"{v['lineitems']:,}".replace(",", "."),
        ])
    t = Table(rows, colWidths=[5.5 * cm, 3.5 * cm, 2.5 * cm, 2.8 * cm, 2.2 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_TEAL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, BRAND_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _rubric_table(scores: dict[str, Any] | None) -> Table | None:
    if not scores or scores.get("_parse_error"):
        return None
    dims = ["NUMERIC_FIDELITY", "PEER_COMPARISON", "ACTIONABILITY", "CLARITY", "PII_COMPLIANCE"]
    header = [d.replace("_", " ").title() for d in dims]
    values = []
    for d in dims:
        entry = scores.get(d) or {}
        s = entry.get("score") if isinstance(entry, dict) else None
        values.append(f"{s}/5" if s is not None else "—")
    t = Table([header, values], colWidths=[3.5 * cm] * 5)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_GREY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (-1, 1), 12),
        ("TEXTCOLOR", (0, 1), (-1, 1), BRAND_BLUE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("BACKGROUND", (0, 1), (-1, 1), BRAND_LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.4, BRAND_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def _parse_narrative(text: str) -> dict[str, str]:
    """Split LLM output by section header. Best-effort — falls back to one block."""
    if not text:
        return {}
    pattern = re.compile(
        r"(?:^|\n)\s*(?:\d+\.\s*)?(" + "|".join(re.escape(h) for h in SECTION_HEADERS) + r")\s*\n",
        flags=re.IGNORECASE,
    )
    matches = list(pattern.finditer(text))
    if not matches:
        return {"FULL TEXT": text.strip()}
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        title = m.group(1).upper()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections[title] = body
    return sections


def _paragraphs(text: str, styles: dict[str, ParagraphStyle]) -> list:
    """Render free-text into a list of Paragraphs / bullet items."""
    out: list = []
    for raw_para in re.split(r"\n{2,}", text.strip()):
        chunk = raw_para.strip()
        if not chunk:
            continue
        # Bulleted list?
        bullet_lines = [
            line.lstrip("-•* ").strip()
            for line in chunk.splitlines()
            if line.lstrip().startswith(("-", "•", "*"))
        ]
        if bullet_lines and len(bullet_lines) == len(chunk.splitlines()):
            for b in bullet_lines:
                out.append(Paragraph(_html_safe(b), styles["bullet"], bulletText="•"))
        else:
            out.append(Paragraph(_html_safe(chunk).replace("\n", "<br/>"), styles["body"]))
    return out


def _html_safe(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ---- header / footer painters ----

def _header_footer(canvas, doc) -> None:  # noqa: ANN001 — reportlab API
    canvas.saveState()
    page_w, page_h = A4
    # Header band
    canvas.setFillColor(BRAND_BLUE)
    canvas.rect(0, page_h - 12 * mm, page_w, 12 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(15 * mm, page_h - 8 * mm, "SMARTEMIS")
    canvas.setFont("Helvetica", 8)
    title = getattr(doc, "_smartemis_title", "Clinic performance report")
    canvas.drawRightString(page_w - 15 * mm, page_h - 8 * mm, title)
    # Footer
    canvas.setFillColor(BRAND_GREY)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(15 * mm, 8 * mm, "Confidential — Smartemis network. Pseudonymized data.")
    canvas.drawRightString(page_w - 15 * mm, 8 * mm, f"Page {doc.page}")
    canvas.restoreState()


def build_clinic_report_pdf(
    *,
    clinic_site: str,
    period_start: str,
    period_end: str,
    report_text: str,
    kpi_payload: dict[str, Any],
    peer_benchmarks: dict[str, Any] | None = None,
    rubric_scores: dict[str, Any] | None = None,
    model_id: str = "",
    report_id: int | None = None,
    generated_at: datetime | None = None,
) -> bytes:
    """Build the full PDF and return it as bytes."""
    peers = peer_benchmarks or {}
    generated_at = generated_at or datetime.now(timezone.utc)
    styles = _styles()

    buf = io.BytesIO()
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=18 * mm, bottomMargin=15 * mm,
        title=f"Smartemis report — {clinic_site}",
        author="Smartemis Consulting",
    )
    doc._smartemis_title = f"Clinic {clinic_site} · {period_start} → {period_end}"

    page_frame = Frame(
        doc.leftMargin, doc.bottomMargin,
        doc.width, doc.height - 4 * mm,
        id="main", showBoundary=0,
    )
    doc.addPageTemplates([
        PageTemplate(id="branded", frames=[page_frame], onPage=_header_footer),
    ])

    story: list = []

    # ---------- Cover ----------
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph("Smartemis", styles["title"]))
    story.append(Paragraph("Clinic performance report", styles["subtitle"]))
    story.append(Spacer(1, 1.4 * cm))

    cover_rows = [
        ["Clinic", clinic_site],
        ["Reporting period", f"{period_start}  →  {period_end}"],
        ["Report ID", f"#{report_id}" if report_id else "—"],
        ["Generated", generated_at.strftime("%Y-%m-%d %H:%M UTC")],
        ["Model", model_id or "—"],
        ["Data class", "Pseudonymized — GDPR Art. 4(5)"],
    ]
    cover_table = Table(
        [[Paragraph(label, styles["cover_label"]), Paragraph(value, styles["cover_value"])]
         for label, value in cover_rows],
        colWidths=[5 * cm, 12 * cm],
    )
    cover_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, BRAND_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(cover_table)

    if rubric_scores:
        rt = _rubric_table(rubric_scores)
        if rt is not None:
            story.append(Spacer(1, 1.2 * cm))
            story.append(Paragraph("Auto-evaluated rubric", styles["h2"]))
            story.append(rt)

    story.append(PageBreak())

    # ---------- Page 2: KPI tiles + monthly revenue ----------
    story.append(Paragraph("1. Performance overview", styles["h1"]))
    story.append(_kpi_tiles(kpi_payload, styles))
    story.append(Spacer(1, 8))

    monthly_chart = _embed_chart(charts.chart_monthly_revenue(kpi_payload.get("monthly_revenue", {})))
    if monthly_chart:
        story.append(monthly_chart)

    if peers:
        story.append(Spacer(1, 6))
        story.append(Paragraph("Peer comparison", styles["h2"]))
        story.append(_peer_compare_table(kpi_payload, peers, styles))

    sections = _parse_narrative(report_text)

    if sections.get("EXECUTIVE SUMMARY"):
        story.append(Spacer(1, 8))
        story.append(Paragraph("2. Executive summary", styles["h1"]))
        story.extend(_paragraphs(sections["EXECUTIVE SUMMARY"], styles))

    story.append(PageBreak())

    # ---------- Revenue + pricing ----------
    story.append(Paragraph("3. Revenue mix and pricing", styles["h1"]))
    mix_chart = _embed_chart(charts.chart_revenue_mix(kpi_payload.get("revenue_share_by_item_type", {})), width_cm=12)
    if mix_chart:
        story.append(mix_chart)
    for key in ("REVENUE PERFORMANCE", "PRICING & GOT FACTOR ANALYSIS", "PRICING AND GOT FACTOR ANALYSIS"):
        if sections.get(key):
            story.extend(_paragraphs(sections[key], styles))

    story.append(Spacer(1, 6))
    story.append(Paragraph("Top item groups by revenue", styles["h2"]))
    top_groups_chart = _embed_chart(charts.chart_top_item_groups(kpi_payload.get("top_item_groups_by_revenue", [])))
    if top_groups_chart:
        story.append(top_groups_chart)

    story.append(PageBreak())

    # ---------- Case & species mix ----------
    story.append(Paragraph("4. Case & species mix", styles["h1"]))
    species_chart = _embed_chart(charts.chart_species_mix(kpi_payload.get("species_mix_revenue", {})))
    if species_chart:
        story.append(species_chart)
    for key in ("CASE & SPECIES MIX", "CASE AND SPECIES MIX"):
        if sections.get(key):
            story.extend(_paragraphs(sections[key], styles))

    story.append(PageBreak())

    # ---------- Vet productivity ----------
    story.append(Paragraph("5. Vet productivity (pseudonymized)", styles["h1"]))
    vets = kpi_payload.get("vet_productivity", [])
    vet_chart = _embed_chart(charts.chart_vet_productivity(vets))
    if vet_chart:
        story.append(vet_chart)
    if vets:
        story.append(Spacer(1, 6))
        story.append(_vet_table(vets))
    if sections.get("VET PRODUCTIVITY"):
        story.append(Spacer(1, 6))
        story.extend(_paragraphs(sections["VET PRODUCTIVITY"], styles))

    story.append(PageBreak())

    # ---------- Payment & collections ----------
    story.append(Paragraph("6. Payment & collections", styles["h1"]))
    pay_chart = _embed_chart(
        charts.chart_payment_status(
            kpi_payload.get("pct_paid", 0.0), kpi_payload.get("unpaid_revenue", 0.0)
        ),
        width_cm=10,
    )
    if pay_chart:
        story.append(pay_chart)
    for key in ("PAYMENT & COLLECTIONS", "PAYMENT AND COLLECTIONS"):
        if sections.get(key):
            story.extend(_paragraphs(sections[key], styles))

    # ---------- Recommendations ----------
    if sections.get("RECOMMENDATIONS"):
        story.append(Spacer(1, 10))
        story.append(KeepTogether([
            Paragraph("7. Recommendations", styles["h1"]),
            *_paragraphs(sections["RECOMMENDATIONS"], styles),
        ]))

    # If parsing failed, dump full LLM text on its own page
    if "FULL TEXT" in sections:
        story.append(PageBreak())
        story.append(Paragraph("Consulting analysis (full text)", styles["h1"]))
        story.extend(_paragraphs(sections["FULL TEXT"], styles))

    # ---------- Appendix ----------
    story.append(PageBreak())
    story.append(Paragraph("A. KPI appendix", styles["h1"]))
    story.append(Paragraph(
        "Full KPI payload that fed the LLM. All identifiers are pseudonyms — vet names, "
        "invoice numbers, treatment numbers, customer postcodes and pet birthdates are "
        "either replaced with HMAC-SHA256 pseudonyms or generalized to satisfy GDPR "
        "data-minimization requirements.",
        styles["small"],
    ))
    story.append(Spacer(1, 6))
    story.append(_appendix_table(kpi_payload))

    doc.build(story)
    return buf.getvalue()


def _appendix_table(kpis: dict[str, Any]) -> Table:
    rows = [["Metric", "Value"]]

    def add(label: str, value: Any) -> None:
        rows.append([label, str(value)])

    add("Period", f"{kpis.get('period_start')} → {kpis.get('period_end')}")
    add("Total revenue (net)", _eur(kpis.get("total_revenue_net", 0.0)))
    add("Invoice count", kpis.get("invoice_count", 0))
    add("Lineitem count", kpis.get("lineitem_count", 0))
    add("Avg invoice value", _eur(kpis.get("avg_invoice_value", 0.0)))
    if kpis.get("avg_got_factor") is not None:
        add("Avg GOT factor", f"{kpis['avg_got_factor']:.3f}")
        add("GOT factor p25 / p75",
            f"{kpis.get('got_factor_p25', 0):.3f} / {kpis.get('got_factor_p75', 0):.3f}")
    add("% paid", _pct(kpis.get("pct_paid", 0.0)))
    add("Unpaid revenue", _eur(kpis.get("unpaid_revenue", 0.0)))
    add("Vet count (top set)", len(kpis.get("vet_productivity", [])))
    add("PLZ regions reached", len(kpis.get("geo_reach_plz_prefix", {})))

    t = Table(rows, colWidths=[7 * cm, 10 * cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, BRAND_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t
