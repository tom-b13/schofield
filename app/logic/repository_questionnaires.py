"""Questionnaire-related data access helpers."""

from __future__ import annotations

from sqlalchemy import text as sql_text

from app.db.base import get_engine


def get_questionnaire_metadata(questionnaire_id: str) -> tuple[str, str] | None:
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            sql_text(
                "SELECT name, description FROM questionnaires WHERE questionnaire_id = :id"
            ),
            {"id": questionnaire_id},
        ).fetchone()
    if not row:
        return None
    return str(row[0]), str(row[1])


def questionnaire_exists(questionnaire_id: str) -> bool:
    eng = get_engine()
    with eng.connect() as conn:
        exists = conn.execute(
            sql_text("SELECT 1 FROM questionnaires WHERE questionnaire_id = :id"),
            {"id": questionnaire_id},
        ).fetchone()
    return exists is not None

