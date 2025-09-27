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

logger = logging.getLogger(__name__)


def _db_url() -> str:
    return (
        os.getenv("DATABASE_URL")
        or os.getenv("TEST_DATABASE_URL")
        or "sqlite+pysqlite:///:memory:"
    )


def get_engine(url: str | None = None) -> Engine:
    url = url or _db_url()
    return create_engine(url, future=True, pool_pre_ping=True)


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
