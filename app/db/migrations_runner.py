"""Sequential SQL migrations runner for EPIC-A (001–004).

Design goals:
- Deterministic application order with a simple JSON journal artefact written to
  `migrations/_journal.json` listing filenames and ISO-8601 UTC timestamps.
- No direct execution of SQL in this epic; we only read files and can expose
  their contents to a calling layer that owns DB execution.

Avoids embedding any DDL tokens in code. SQL is kept exclusively in files.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional
import json


MIGRATIONS_DIR = Path("migrations")
JOURNAL_PATH = MIGRATIONS_DIR / "_journal.json"


@dataclass(frozen=True)
class Migration:
    filename: str
    sql: str


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_migrations() -> List[Migration]:
    order = [
        "001_init.sql",
        "002_constraints.sql",
        "003_indexes.sql",
    ]
    migrations: List[Migration] = []
    for name in order:
        path = MIGRATIONS_DIR / name
        sql = path.read_text(encoding="utf-8")
        migrations.append(Migration(filename=f"migrations/{name}", sql=sql))
    return migrations


def write_journal(entries: Iterable[dict]) -> None:
    data = list(entries)
    JOURNAL_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def apply_migrations(executor: Optional[callable] = None) -> List[dict]:
    """Apply migrations in order using an optional executor(sql: str) -> None.

    Returns the journal entries written to disk.
    """
    migrations = load_migrations()
    journal: List[dict] = []
    for m in migrations:
        if executor:
            executor(m.sql)
        journal.append({"filename": m.filename, "applied_at": _utcnow_iso()})
    write_journal(journal)
    return journal


__all__ = [
    "Migration",
    "load_migrations",
    "apply_migrations",
    "write_journal",
]

