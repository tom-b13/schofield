"""SQLAlchemy engine and session dependency.

The service targets PostgreSQL in production but supports SQLite for local
development and CI. No declarative models are defined here; this module only
manages connection lifecycle.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

logger = logging.getLogger(__name__)


def _db_url() -> str:
    return (
        os.getenv("TEST_DATABASE_URL")
        or os.getenv("DATABASE_URL")
        or "sqlite+pysqlite:///:memory:"
    )


# Module-level cached Engine to ensure a single shared connection/engine
_ENGINE: Engine | None = None
_ENGINE_URL: str | None = None


def get_engine(url: str | None = None) -> Engine:
    """Return a singleton SQLAlchemy Engine for the given URL.

    Reuses a module-level Engine so repositories share the same connection.
    For SQLite in-memory URLs, use a StaticPool to keep a single connection
    alive across sessions and threads during tests.
    """
    global _ENGINE, _ENGINE_URL
    resolved_url = url or _db_url()

    if _ENGINE is None or _ENGINE_URL != resolved_url:
        kwargs: dict = {"future": True, "pool_pre_ping": True}
        if resolved_url.startswith("sqlite") and ":memory:" in resolved_url:
            # Keep a single in-memory DB connection shared across the process
            kwargs.update({
                "poolclass": StaticPool,
                "connect_args": {"check_same_thread": False},
            })
        _ENGINE = create_engine(resolved_url, **kwargs)
        _ENGINE_URL = resolved_url

    return _ENGINE


def get_sessionmaker(engine: Engine | None = None) -> sessionmaker:
    engine = engine or get_engine()
    return sessionmaker(bind=engine, future=True)


@contextmanager
def session_dependency() -> Generator:
    """FastAPI-style dependency yielding a SQLAlchemy session."""
    Session = get_sessionmaker()
    session = Session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        logger.error("DB session error; transaction rolled back", exc_info=True)
        raise
    finally:
        session.close()
