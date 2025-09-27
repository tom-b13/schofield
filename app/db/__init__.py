"""Database bootstrap utilities for EPIC-B — Questionnaire Service.

This module exposes convenience imports for engine/session construction and an
optional migrations runner that applies SQL files from the local migrations/
directory. The DB layer is intentionally minimal and does not leak ORM models
into route handlers.
"""

from app.db.base import get_engine, get_sessionmaker, session_dependency
from app.db.migrations_runner import apply_migrations

__all__ = [
    "get_engine",
    "get_sessionmaker",
    "session_dependency",
    "apply_migrations",
]
