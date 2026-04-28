"""Matplotlib chart helpers used by the PDF exporter.

All chart functions take pre-computed KPI dicts and return PNG bytes. They run
on the non-interactive Agg backend so they're safe inside a FastAPI handler.

Smartemis brand palette is defined once at the top — change it here and every
chart updates.
"""
from __future__ import annotations

import io
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick

# Smartemis brand palette
SMARTEMIS_BLUE = "#1e3a8a"
SMARTEMIS_ACCENT = "#0ea5e9"
SMARTEMIS_TEAL = "#0d9488"
SMARTEMIS_GOLD = "#d97706"
SMARTEMIS_RED = "#dc2626"
SMARTEMIS_GREEN = "#16a34a"
SMARTEMIS_GREY = "#475569"

CATEGORICAL = [
    SMARTEMIS_BLUE,
    SMARTEMIS_ACCENT,
    SMARTEMIS_TEAL,
    SMARTEMIS_GOLD,
    SMARTEMIS_RED,
    SMARTEMIS_GREEN,
    SMARTEMIS_GREY,
    "#9333ea",
]

EUR = "€"


def _apply_style(ax: plt.Axes, *, title: str | None = None) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#cbd5e1")
    ax.tick_params(colors="#475569", labelsize=9)
    ax.grid(axis="y", linestyle=":", color="#e2e8f0", linewidth=0.6)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, fontsize=11, color=SMARTEMIS_BLUE, fontweight="bold", pad=10)


def _figure_to_png(fig: plt.Figure, *, dpi: int = 150) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def chart_monthly_revenue(monthly: dict[str, float]) -> bytes | None:
    if not monthly:
        return None
    items = sorted(monthly.items())
    months = [k for k, _ in items]
    values = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(8, 3.2))
    ax.bar(months, values, color=SMARTEMIS_BLUE, edgecolor="white", linewidth=0.5)
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"{x:,.0f} {EUR}"))
    ax.set_ylabel("Net revenue", fontsize=9, color="#475569")
    ax.tick_params(axis="x", rotation=30)
    _apply_style(ax, title="Monthly revenue")
    fig.tight_layout()
    return _figure_to_png(fig)


def chart_revenue_mix(share_by_type: dict[str, float]) -> bytes | None:
    if not share_by_type:
        return None
    labels = list(share_by_type.keys())
    sizes = list(share_by_type.values())
    fig, ax = plt.subplots(figsize=(5, 3.5))
    wedges, _texts, autotexts = ax.pie(
        sizes,
        labels=labels,
        colors=CATEGORICAL[: len(labels)],
        autopct="%1.0f%%",
        pctdistance=0.78,
        startangle=90,
        wedgeprops={"width": 0.45, "edgecolor": "white", "linewidth": 2},
        textprops={"fontsize": 9, "color": "#1e293b"},
    )
    for at in autotexts:
        at.set_color("white")
        at.set_fontweight("bold")
    ax.set_title("Revenue mix by item type", fontsize=11, color=SMARTEMIS_BLUE, fontweight="bold")
    fig.tight_layout()
    return _figure_to_png(fig)


def chart_species_mix(species_rev: dict[str, float]) -> bytes | None:
    if not species_rev:
        return None
    items = sorted(species_rev.items(), key=lambda kv: kv[1], reverse=True)
    labels = [k for k, _ in items]
    values = [v for _, v in items]
    fig, ax = plt.subplots(figsize=(6, 3.0))
    bars = ax.barh(labels, values, color=SMARTEMIS_TEAL, edgecolor="white")
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"{x:,.0f} {EUR}"))
    for bar, v in zip(bars, values, strict=False):
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2,
                f"  {v:,.0f} {EUR}", va="center", fontsize=8, color="#475569")
    _apply_style(ax, title="Revenue by species")
    fig.tight_layout()
    return _figure_to_png(fig)


def chart_vet_productivity(vets: list[dict[str, Any]]) -> bytes | None:
    if not vets:
        return None
    top = vets[:8]
    labels = [v["vet_id"][:18] for v in top]  # truncate the pseudonymous IDs visually
    revenues = [v["revenue"] for v in top]
    rpi = [v["revenue_per_invoice"] for v in top]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8, 3.4), gridspec_kw={"width_ratios": [1.4, 1]})
    ax1.barh(labels, revenues, color=SMARTEMIS_BLUE, edgecolor="white")
    ax1.invert_yaxis()
    ax1.xaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"{x:,.0f} {EUR}"))
    _apply_style(ax1, title="Total revenue by vet (pseudonymized)")

    ax2.barh(labels, rpi, color=SMARTEMIS_ACCENT, edgecolor="white")
    ax2.invert_yaxis()
    ax2.xaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"{x:,.0f} {EUR}"))
    ax2.set_yticklabels([])
    _apply_style(ax2, title="Revenue per invoice")

    fig.tight_layout()
    return _figure_to_png(fig)


def chart_top_item_groups(groups: list[dict[str, Any]]) -> bytes | None:
    if not groups:
        return None
    top = groups[:10]
    labels = [g["item_group"] for g in top]
    revenues = [g["revenue"] for g in top]
    fig, ax = plt.subplots(figsize=(8, 3.6))
    ax.barh(labels, revenues, color=SMARTEMIS_GOLD, edgecolor="white")
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(mtick.FuncFormatter(lambda x, _: f"{x:,.0f} {EUR}"))
    _apply_style(ax, title="Top item groups by revenue")
    fig.tight_layout()
    return _figure_to_png(fig)


def chart_payment_status(pct_paid: float, unpaid_revenue: float) -> bytes | None:
    paid = max(0.0, min(1.0, pct_paid))
    unpaid = 1.0 - paid
    fig, ax = plt.subplots(figsize=(4, 3.2))
    ax.pie(
        [paid, unpaid],
        labels=[f"Paid ({paid * 100:.1f}%)", f"Unpaid ({unpaid * 100:.1f}%)"],
        colors=[SMARTEMIS_GREEN, SMARTEMIS_RED],
        startangle=90,
        wedgeprops={"width": 0.4, "edgecolor": "white", "linewidth": 2},
        textprops={"fontsize": 9, "color": "#1e293b"},
    )
    ax.set_title(
        f"Payment status\nUnpaid revenue: {unpaid_revenue:,.0f} {EUR}",
        fontsize=11, color=SMARTEMIS_BLUE, fontweight="bold",
    )
    fig.tight_layout()
    return _figure_to_png(fig)
