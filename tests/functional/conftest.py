from __future__ import annotations

"""Functional test bootstrap for Epic K contract tests.

For functional (contract) tests, use an in‑memory SQLite database shared across
the process. Apply the SQLite‑specific migrations once at session start so the
schema exists before tests create the FastAPI app via TestClient.

This file is intentionally scoped under tests/functional/ so Behave (integration)
and unit tests are unaffected.
"""

import os
import pathlib
import pytest

# Ensure the app points to a shared in‑memory SQLite before any imports of app.main
# Prefer the generic SQLite URL for maximum compatibility with the stdlib driver
_ROOT = pathlib.Path(__file__).resolve().parents[2]
_DB_FILE = _ROOT / "tmp" / "functional_tests.db"
_DB_FILE.parent.mkdir(parents=True, exist_ok=True)
try:
    if _DB_FILE.exists():
        _DB_FILE.unlink()
except Exception:
    pass

# Use a file-backed SQLite DB to ensure persistence across connections
os.environ["TEST_DATABASE_URL"] = f"sqlite:///{_DB_FILE}"
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
# Disable app startup auto-migrations; we will apply SQLite migrations explicitly
os.environ["AUTO_APPLY_MIGRATIONS"] = "0"


def _apply_sqlite_migrations() -> None:
    """Apply SQLite-compatible migrations to the shared in-memory engine."""
    from app.db.base import get_engine
    from app.db.migrations_runner import apply_migrations

    engine = get_engine(os.environ["TEST_DATABASE_URL"])
    sqlite_migrations_dir = _ROOT / "sqlite_migrations"

    # Ensure a clean migration journal so core schema is applied on this DB
    journal = sqlite_migrations_dir / "_journal.json"
    try:
        if journal.exists():
            journal.unlink()
    except Exception:
        pass
    apply_migrations(engine, migrations_dir=str(sqlite_migrations_dir))


@pytest.fixture(scope="session", autouse=True)
def functional_sqlite_bootstrap() -> None:
    """Session-level bootstrap: apply migrations once for the shared DB."""
    _apply_sqlite_migrations()
    # Nothing to tear down; in-memory DB lifecycle is tied to process/engine
    yield
