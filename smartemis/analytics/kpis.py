"""Clinic-level KPIs from pseudonymized line-item data.

Output is the LLM's input: keep it PII-free, deterministic, and compact.
The LLM must never see raw rows — only these aggregates.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import pandas as pd


@dataclass
class ClinicKPIs:
    clinic_site: str
    period_start: str
    period_end: str

    total_revenue_net: float
    invoice_count: int
    lineitem_count: int
    avg_invoice_value: float

    revenue_by_item_type: dict[str, float]
    revenue_share_by_item_type: dict[str, float]

    avg_got_factor: float | None
    got_factor_p25: float | None
    got_factor_p75: float | None

    species_mix_revenue: dict[str, float]
    species_mix_volume: dict[str, int]

    top_item_groups_by_revenue: list[dict[str, Any]]
    top_brands_by_revenue: list[dict[str, Any]]
    case_note_mix: dict[str, float]

    vet_productivity: list[dict[str, Any]]          # pseudonymized vet_id only
    geo_reach_plz_prefix: dict[str, float]          # generalized plz_prefix → revenue

    pct_paid: float
    unpaid_revenue: float

    monthly_revenue: dict[str, float] = field(default_factory=dict)

    def as_prompt_payload(self) -> dict[str, Any]:
        """Compact dict shipped into the LLM prompt. No PII."""
        return asdict(self)


def _pct_shares(series: pd.Series) -> dict[str, float]:
    total = series.sum()
    if total == 0:
        return {}
    return {str(k): round(float(v) / float(total), 4) for k, v in series.items()}


def compute_clinic_kpis(
    df: pd.DataFrame,
    clinic_site: str,
    top_n: int = 10,
) -> ClinicKPIs:
    """Compute KPIs for one clinic over the full period present in `df`."""
    clinic_df = df[df["clinic_site"] == clinic_site]
    if clinic_df.empty:
        raise ValueError(f"No rows for clinic_site={clinic_site}")

    period_start = clinic_df["treatment_date"].min()
    period_end = clinic_df["treatment_date"].max()

    invoices = clinic_df.groupby("invoice_id")
    total_rev = float(clinic_df["revenue_net"].sum())
    invoice_count = int(clinic_df["invoice_id"].nunique())
    lineitem_count = int(len(clinic_df))
    avg_invoice = total_rev / invoice_count if invoice_count else 0.0

    rev_by_type = clinic_df.groupby("item_type")["revenue_net"].sum().round(2)
    share_by_type = _pct_shares(rev_by_type)

    leistungen = clinic_df[clinic_df["item_type"] == "Leistungen"]
    factors = leistungen["got_factor"].dropna()
    avg_faktor = float(factors.mean()) if len(factors) else None
    q25 = float(factors.quantile(0.25)) if len(factors) else None
    q75 = float(factors.quantile(0.75)) if len(factors) else None

    species_rev = clinic_df.groupby("species")["revenue_net"].sum().round(2)
    species_vol = clinic_df.groupby("species")["invoice_id"].nunique()

    top_groups = (
        clinic_df.groupby("item_group")["revenue_net"].sum().round(2)
        .sort_values(ascending=False).head(top_n)
    )
    top_groups_rows = [
        {"item_group": g, "revenue": float(v), "share": float(v) / total_rev if total_rev else 0.0}
        for g, v in top_groups.items()
    ]

    top_brands = (
        clinic_df.groupby("brand")["revenue_net"].sum().round(2)
        .sort_values(ascending=False).head(top_n)
    )
    top_brands_rows = [
        {"brand": b, "revenue": float(v)} for b, v in top_brands.items() if b
    ]

    case_mix = _pct_shares(clinic_df.groupby("case_note_scrubbed")["revenue_net"].sum())

    vet_rev = (
        clinic_df.groupby("vet_id")
        .agg(
            revenue=("revenue_net", "sum"),
            invoices=("invoice_id", "nunique"),
            lineitems=("invoice_id", "count"),
        )
        .round(2)
        .sort_values("revenue", ascending=False)
        .head(top_n)
    )
    vet_rows = [
        {
            "vet_id": idx,
            "revenue": float(r.revenue),
            "invoices": int(r.invoices),
            "lineitems": int(r.lineitems),
            "revenue_per_invoice": float(r.revenue / r.invoices) if r.invoices else 0.0,
        }
        for idx, r in vet_rev.iterrows()
    ]

    geo = clinic_df.groupby("plz_prefix")["revenue_net"].sum().round(2).sort_values(ascending=False)
    geo_dict = {str(k): float(v) for k, v in geo.items() if k}

    invoice_paid = invoices["paid"].max()
    invoice_revenue = invoices["revenue_net"].sum()
    paid_count = int(invoice_paid.sum()) if len(invoice_paid) else 0
    pct_paid = paid_count / invoice_count if invoice_count else 0.0
    unpaid_revenue = float(invoice_revenue[~invoice_paid].sum()) if len(invoice_paid) else 0.0

    monthly = (
        clinic_df.assign(month=clinic_df["treatment_date"].map(lambda d: f"{d.year}-{d.month:02d}"))
        .groupby("month")["revenue_net"].sum().round(2)
    )

    return ClinicKPIs(
        clinic_site=clinic_site,
        period_start=str(period_start) if period_start else "",
        period_end=str(period_end) if period_end else "",
        total_revenue_net=round(total_rev, 2),
        invoice_count=invoice_count,
        lineitem_count=lineitem_count,
        avg_invoice_value=round(avg_invoice, 2),
        revenue_by_item_type={k: float(v) for k, v in rev_by_type.items()},
        revenue_share_by_item_type=share_by_type,
        avg_got_factor=round(avg_faktor, 3) if avg_faktor is not None else None,
        got_factor_p25=round(q25, 3) if q25 is not None else None,
        got_factor_p75=round(q75, 3) if q75 is not None else None,
        species_mix_revenue={k: float(v) for k, v in species_rev.items()},
        species_mix_volume={k: int(v) for k, v in species_vol.items()},
        top_item_groups_by_revenue=top_groups_rows,
        top_brands_by_revenue=top_brands_rows,
        case_note_mix=case_mix,
        vet_productivity=vet_rows,
        geo_reach_plz_prefix=geo_dict,
        pct_paid=round(pct_paid, 4),
        unpaid_revenue=round(unpaid_revenue, 2),
        monthly_revenue={str(k): float(v) for k, v in monthly.items()},
    )


def compute_peer_benchmarks(df: pd.DataFrame) -> dict[str, Any]:
    """Network-wide benchmarks a single clinic can be compared against."""
    by_clinic = df.groupby("clinic_site").agg(
        revenue=("revenue_net", "sum"),
        invoices=("invoice_id", "nunique"),
        avg_factor=("got_factor", "mean"),
        pct_paid=("paid", "mean"),
    )
    if by_clinic.empty:
        return {}

    return {
        "network_total_revenue": round(float(by_clinic["revenue"].sum()), 2),
        "clinic_count": int(len(by_clinic)),
        "median_revenue": round(float(by_clinic["revenue"].median()), 2),
        "p25_revenue": round(float(by_clinic["revenue"].quantile(0.25)), 2),
        "p75_revenue": round(float(by_clinic["revenue"].quantile(0.75)), 2),
        "median_avg_factor": round(float(by_clinic["avg_factor"].median()), 3),
        "median_pct_paid": round(float(by_clinic["pct_paid"].median()), 4),
    }
