"""Questionnaire-related data access helpers."""

from __future__ import annotations

from sqlalchemy import text as sql_text
from typing import Iterable, List, Dict, Any

from app.db.base import get_engine


def get_questionnaire_metadata(questionnaire_id: str) -> tuple[str, str] | None:
    eng = get_engine()
    with eng.connect() as conn:
        # Primary: test schema table name 'questionnaire'
        try:
            row = conn.execute(
                sql_text(
                    "SELECT name, description FROM questionnaire WHERE questionnaire_id = :id"
                ),
                {"id": questionnaire_id},
            ).fetchone()
        except Exception:
            # Fallback to legacy pluralised table if present
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
        try:
            exists = conn.execute(
                sql_text("SELECT 1 FROM questionnaire WHERE questionnaire_id = :id"),
                {"id": questionnaire_id},
            ).fetchone()
        except Exception:
            exists = conn.execute(
                sql_text("SELECT 1 FROM questionnaires WHERE questionnaire_id = :id"),
                {"id": questionnaire_id},
            ).fetchone()
    return exists is not None


def list_questions_for_questionnaire_export(questionnaire_id: str) -> Iterable[dict]:
    """Return rows for CSV export for a questionnaire (v1.0 contract).

    Returns dictionaries with keys exactly:
      external_qid, screen_key, question_order, question_text,
      answer_kind, mandatory, placeholder_code, options

    Ordering: by question_order asc (tie-breaker by question_id asc).
    """
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(
            sql_text(
                """
                SELECT q.question_id,
                       q.external_qid,
                       q.screen_key,
                       q.question_order,
                       q.question_text,
                       q.answer_kind AS answer_kind,
                       q.mandatory,
                       q.placeholder_code
                FROM questionnaire_question q
                JOIN screen s ON s.screen_key = q.screen_key
                WHERE s.questionnaire_id = :qid
                ORDER BY q.question_order ASC, q.question_id ASC
                """
            ),
            {"qid": questionnaire_id},
        ).mappings().all()

    # Map to required keys only
    result: List[Dict[str, Any]] = []
    for r in rows:
        result.append(
            {
                "question_id": r.get("question_id"),
                "external_qid": r.get("external_qid"),
                "screen_key": r.get("screen_key"),
                "question_order": int(r.get("question_order", 0) or 0),
                "question_text": r.get("question_text"),
                "answer_kind": r.get("answer_kind"),
                "mandatory": bool(r.get("mandatory", 0)),
                "placeholder_code": r.get("placeholder_code") or "",
                # Options will be populated by caller if needed; default to empty string
                "options": "",
            }
        )
    return result
