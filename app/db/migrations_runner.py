"""Lightweight SQL migrations runner.

Applies .sql files in lexical order from the local `migrations/` directory.
Skips rollback files and records applied filenames in a file-backed journal
(`migrations/_journal.json`) to avoid reapplying the same migration. Intended
for local development and CI; production environments should use Alembic or
the platform's migration mechanism.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable
from datetime import datetime, timezone

from sqlalchemy.engine import Engine
import logging

logger = logging.getLogger(__name__)


def _iter_sql_files(root: Path) -> Iterable[Path]:
    for p in sorted(root.glob("*.sql")):
        # Skip rollback scripts in forward runs
        name = p.name.lower()
        if "rollback" in name or name == "004_rollbacks.sql":
            continue
        yield p


def apply_migrations(engine: Engine, migrations_dir: str | os.PathLike[str] = "migrations") -> None:
    root = Path(migrations_dir)
    if not root.exists():  # pragma: no cover - optional
        return

    journal_path = root / "_journal.json"

    # Load journal entries (file-backed), tolerate missing/invalid file
    journal_entries: list[dict] = []
    applied: set[str] = set()
    if journal_path.exists():
        try:
            data = json.loads(journal_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                journal_entries = [e for e in data if isinstance(e, dict)]
                applied = {Path(e.get("filename", "")).name for e in journal_entries if isinstance(e.get("filename"), str)}
        except Exception:  # pragma: no cover - start fresh on any parse error
            logger.error("migration_journal_parse_failed path=%s", str(journal_path), exc_info=True)
            journal_entries = []
            applied = set()

    with engine.begin() as conn:
        for sql_path in _iter_sql_files(root):
            fname = sql_path.name
            if fname in applied:
                continue
            sql = sql_path.read_text(encoding="utf-8")
            if not sql.strip():
                continue
            conn.exec_driver_sql(sql)

            # Append to file-backed journal and write atomically
            entry = {
                "filename": f"migrations/{fname}",
                "applied_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            journal_entries.append(entry)
            _atomic_write_json(journal_path, journal_entries)


def _atomic_write_json(path: Path, content: list[dict]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp_path, path)
