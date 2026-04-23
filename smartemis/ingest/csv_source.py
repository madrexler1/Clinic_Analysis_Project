from __future__ import annotations

from pathlib import Path

import pandas as pd


class CSVSource:
    """Reads Smartemis exports. Semicolon-delimited by default (German Excel)."""

    def __init__(self, path: Path | str, *, delimiter: str = ";", encoding: str = "utf-8"):
        self.path = Path(path)
        self.delimiter = delimiter
        self.encoding = encoding

    def read_raw(self) -> pd.DataFrame:
        if not self.path.exists():
            raise FileNotFoundError(
                f"CSV not found: {self.path}. "
                "Generate synthetic data with `python -m synthetic_data.generate`."
            )
        return pd.read_csv(self.path, sep=self.delimiter, encoding=self.encoding, dtype=str)
