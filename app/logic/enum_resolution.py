"""Enum resolution helpers.

Resolves enum_single submissions to a canonical option_id for a question.
"""

from __future__ import annotations

from typing import Any, Dict
from sqlalchemy import text as sql_text

from app.db.base import get_engine


def resolve_enum_option(question_id: str, *, option_id: str | None = None, value_token: str | None = None) -> str | None:
    """Resolve to canonical option_id for enum_single submissions.

    Accepts either an explicit option_id or a value token; returns a matching
    option_id if found, else None.
    """
    if option_id:
        return option_id
    if not value_token:
        return None
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            sql_text(
                "SELECT option_id FROM answer_option WHERE question_id = :qid AND value = :val LIMIT 1"
            ),
            {"qid": question_id, "val": value_token},
        ).fetchone()
    return str(row[0]) if row else None


__all__ = ["resolve_enum_option"]

