"""PII vault: stores the mapping pseudonym → original value.

Lives server-side only (EC2 + RDS in eu-central-1). Never shipped to the LLM,
never exposed over the API. Enables right-to-erasure (GDPR Art. 17) and the
ability to re-identify for a human reader while keeping the LLM's context
PII-free.

In production, rows here must be encrypted at rest via RDS + KMS CMK.
"""
from __future__ import annotations

import hmac
from hashlib import sha256

from sqlalchemy import String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from smartemis.storage import Base


class PIIMapping(Base):
    __tablename__ = "pii_vault"

    pseudonym: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # vet | invoice | treatment | plz | dob
    original: Mapped[str] = mapped_column(String(256))

    __table_args__ = (UniqueConstraint("kind", "original", name="uq_vault_kind_original"),)


class PIIVault:
    def __init__(self, session: Session, *, salt: str):
        self.session = session
        self._salt = salt.encode("utf-8")

    def pseudonym_for(self, kind: str, original: str) -> str:
        """Deterministic HMAC-SHA256 pseudonym. Same input + salt → same pseudonym."""
        if not original:
            return ""
        digest = hmac.new(self._salt, f"{kind}:{original}".encode("utf-8"), sha256).hexdigest()
        pseudo = f"{kind}_{digest[:12]}"

        existing = self.session.get(PIIMapping, pseudo)
        if existing is None:
            self.session.merge(PIIMapping(pseudonym=pseudo, kind=kind, original=original))
        return pseudo

    def lookup(self, pseudonym: str) -> str | None:
        row = self.session.get(PIIMapping, pseudonym)
        return row.original if row else None

    def purge_original(self, kind: str, original: str) -> int:
        """Right to erasure: remove mapping. Pseudonym stays (downstream rows
        reference it) but the link back to the real identity is severed."""
        stmt = select(PIIMapping).where(PIIMapping.kind == kind, PIIMapping.original == original)
        count = 0
        for row in self.session.scalars(stmt):
            self.session.delete(row)
            count += 1
        return count
