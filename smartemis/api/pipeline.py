"""Thin pipeline wrapper: ingest → pseudonymize → KPIs → report.

Cached at app startup — ingest + pseudonymize are the expensive steps and
are pure functions of the source data.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd

from smartemis.analytics import compute_clinic_kpis, compute_peer_benchmarks
from smartemis.config import get_settings
from smartemis.ingest import load_lineitems
from smartemis.pii import PIIVault, pseudonymize_frame
from smartemis.storage import session_scope


@lru_cache(maxsize=1)
def load_pseudonymized_frame() -> pd.DataFrame:
    """Load + pseudonymize once per process. Swap for a proper cache invalidator
    when we move to Qlik live data."""
    settings = get_settings()
    raw = load_lineitems(settings)
    with session_scope() as s:
        vault = PIIVault(s, salt=settings.pseudo_salt)
        pseudo = pseudonymize_frame(raw, vault)
    return pseudo


def list_clinic_sites() -> list[str]:
    df = load_pseudonymized_frame()
    return sorted(df["clinic_site"].unique().tolist())


def kpis_and_benchmarks(clinic_site: str):
    df = load_pseudonymized_frame()
    kpis = compute_clinic_kpis(df, clinic_site)
    peers = compute_peer_benchmarks(df)
    return kpis, peers
