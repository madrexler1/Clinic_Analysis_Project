"""Shared SQLAlchemy setup. SQLite for local dev; swap `SMARTEMIS_DB_URL` to
a Postgres URL (RDS in eu-central-1) for staging/prod — no code changes needed.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from smartemis.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_engine = create_engine(
    _settings.db_url,
    echo=False,
    connect_args={"check_same_thread": False} if _settings.db_url.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=False)


def init_db() -> None:
    # Import to register tables on the metadata before create_all.
    from smartemis.feedback.models import Feedback, Report  # noqa: F401
    from smartemis.pii.vault import PIIMapping  # noqa: F401

    Base.metadata.create_all(_engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
