"""Pluggable ingestion layer.

Normalizes the Smartemis German column names into a stable English schema the
rest of the pipeline uses. Adding a Qlik source later means implementing
`Source.read_raw()` against the Qlik REST API and reusing `_normalize`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

import pandas as pd

from smartemis.config import Settings, get_settings

# German → canonical English column map. Keep the German names verbatim so
# the same code handles CSV exports and Qlik field labels if Qlik mirrors them.
COLUMN_MAP: dict[str, str] = {
    "Rechnungsnummer": "invoice_no",
    "BehandlungDatum": "treatment_date",
    "Rechnungsdatum": "invoice_date",
    "Artikel Typ": "item_type",
    "Artikel Gruppe": "item_group",
    "Artikel Nummer GOT": "got_code",
    "Tierart": "species",
    "Mitarbeiter": "vet_name",           # PII — pseudonymized downstream
    "Kurzbericht": "case_note",          # may contain free-text PII
    "Brand Name": "brand",
    "KundePLZ": "customer_plz",          # quasi-id — generalized downstream
    "Umsatz netto": "revenue_net",
    "Standort": "clinic_site",
    "TierGeburtsdatum": "pet_dob",       # quasi-id — truncated downstream
    "TierRasse": "breed",
    "Anz. Tiere": "n_animals",
    "Anzahl Behandl.": "n_treatments",
    "Betrag netto": "amount_net",
    "Anzahl/Menge": "quantity",
    "Faktor": "got_factor",
    "BehandlungNummer": "treatment_no",
    "Berechnet": "billed",
    "Bezahlt": "paid",
}


@dataclass(slots=True)
class LineItem:
    """Stable dataclass view of a single invoice line."""
    invoice_no: str
    treatment_date: date
    invoice_date: date
    item_type: str
    item_group: str
    got_code: str
    species: str
    vet_name: str
    case_note: str
    brand: str
    customer_plz: str
    revenue_net: float
    clinic_site: str
    pet_dob: date | None
    breed: str
    n_animals: int
    n_treatments: int
    amount_net: float
    quantity: int
    got_factor: float | None
    treatment_no: str
    billed: bool
    paid: bool


class Source(Protocol):
    """Ingestion source contract. CSV today, Qlik tomorrow."""

    def read_raw(self) -> pd.DataFrame: ...


def _parse_de_date(value: object) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_ja_nein(value: object) -> bool:
    s = str(value).strip().upper()
    return s == "JA"


def _parse_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Rename columns and coerce types. Raw DataFrame in → canonical DataFrame out."""
    missing = [c for c in COLUMN_MAP if c not in df.columns]
    if missing:
        raise ValueError(f"Source missing required columns: {missing}")

    df = df.rename(columns=COLUMN_MAP).copy()

    df["treatment_date"] = df["treatment_date"].map(_parse_de_date)
    df["invoice_date"] = df["invoice_date"].map(_parse_de_date)
    df["pet_dob"] = df["pet_dob"].map(_parse_de_date)
    df["revenue_net"] = df["revenue_net"].map(_parse_float).fillna(0.0)
    df["amount_net"] = df["amount_net"].map(_parse_float).fillna(0.0)
    df["got_factor"] = df["got_factor"].map(_parse_float)
    df["quantity"] = pd.to_numeric(df["quantity"], errors="coerce").fillna(0).astype(int)
    df["n_animals"] = pd.to_numeric(df["n_animals"], errors="coerce").fillna(1).astype(int)
    df["n_treatments"] = pd.to_numeric(df["n_treatments"], errors="coerce").fillna(1).astype(int)
    df["billed"] = df["billed"].map(_parse_ja_nein)
    df["paid"] = df["paid"].map(_parse_ja_nein)

    for col in ("invoice_no", "item_type", "item_group", "got_code", "species",
                "vet_name", "case_note", "brand", "customer_plz", "clinic_site",
                "breed", "treatment_no"):
        df[col] = df[col].fillna("").astype(str).str.strip()

    return df


def load_lineitems(settings: Settings | None = None) -> pd.DataFrame:
    """Entry point: pick the configured source and return a normalized DataFrame."""
    settings = settings or get_settings()
    if settings.source == "csv":
        from .csv_source import CSVSource
        source: Source = CSVSource(settings.csv_path)
    elif settings.source == "qlik":
        from .qlik_source import QlikSource
        source = QlikSource(
            base_url=settings.qlik_base_url or "",
            api_key=settings.qlik_api_key or "",
        )
    else:
        raise ValueError(f"Unknown source: {settings.source}")

    return _normalize(source.read_raw())
