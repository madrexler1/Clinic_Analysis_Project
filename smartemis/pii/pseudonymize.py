"""Apply pseudonymization + generalization to a normalized line-item frame.

PII policy for Smartemis:
  - vet_name         → deterministic pseudonym via vault (can re-identify server-side)
  - invoice_no       → deterministic pseudonym
  - treatment_no     → deterministic pseudonym
  - customer_plz     → generalized to 2-digit prefix ("83109" → "83***"); full PLZ
                       is not retained post-ingest to reduce quasi-identifier risk
  - pet_dob          → truncated to year-month (e.g., 2024-08); enough for age
                       bucketing, insufficient for re-identification
  - case_note        → free-text scanner below; emails/phones/IBANs redacted
                       (tokens like "[REDACTED:email]")

Everything above this layer in the pipeline sees *only* pseudonyms and
generalized fields. The LLM never sees the vault.
"""
from __future__ import annotations

import re

import pandas as pd

from .vault import PIIVault

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{2,4}\)?[\s.-]?){2,4}\d{2,4}")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")


def _scrub_freetext(text: str) -> str:
    if not text:
        return text
    text = _EMAIL.sub("[REDACTED:email]", text)
    text = _IBAN.sub("[REDACTED:iban]", text)
    text = _PHONE.sub("[REDACTED:phone]", text)
    return text


def pseudonymize_frame(df: pd.DataFrame, vault: PIIVault) -> pd.DataFrame:
    """Return a new frame with PII removed/pseudonymized. Safe to ship to LLM."""
    out = df.copy()

    out["vet_id"] = out["vet_name"].map(lambda v: vault.pseudonym_for("vet", v))
    out["invoice_id"] = out["invoice_no"].map(lambda v: vault.pseudonym_for("invoice", v))
    out["treatment_id"] = out["treatment_no"].map(lambda v: vault.pseudonym_for("treatment", v))

    out["plz_prefix"] = out["customer_plz"].map(lambda v: f"{v[:2]}***" if v else "")

    out["pet_dob_ym"] = out["pet_dob"].map(
        lambda d: f"{d.year:04d}-{d.month:02d}" if d is not None else ""
    )

    out["case_note_scrubbed"] = out["case_note"].map(_scrub_freetext)

    out = out.drop(
        columns=["vet_name", "invoice_no", "treatment_no", "customer_plz", "pet_dob", "case_note"],
        errors="ignore",
    )
    return out
