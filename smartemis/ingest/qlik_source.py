"""Qlik Cloud / Qlik Sense REST ingestion — stub.

Fill in the concrete fetch once Smartemis shares the Qlik app ID, the
measure/dimension names, and the auth mode (API key vs OAuth).

Contract: return a DataFrame with the same German column names as the CSV
export so `_normalize` handles it transparently.
"""
from __future__ import annotations

import pandas as pd


class QlikSource:
    def __init__(self, *, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key

    def read_raw(self) -> pd.DataFrame:
        raise NotImplementedError(
            "Qlik source not yet implemented. "
            "Needs: app_id, sheet/table identifier, auth mode. "
            "Once implemented, must return the same German column schema as CSV."
        )
