"""Screen-related data access helpers.

These functions encapsulate SQL queries for screen metadata, questions,
and response counts to keep route handlers free of persistence details.
"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy import text as sql_text

from app.db.base import get_engine


def get_screen_metadata(screen_id: str) -> tuple[str, str] | None:
    """Return (screen_key, title) for a given screen_id, or None if missing."""
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            sql_text("SELECT screen_key, title FROM screens WHERE screen_id = :sid"),
            {"sid": screen_id},
        ).fetchone()
    if not row:
        return None
    return str(row[0]), str(row[1])


def list_questions_for_screen(screen_key: str) -> list[dict]:
    """List questions bound to a screen, ordered deterministically and deduplicated.

    Returns a list of dicts containing:
    - question_id, external_qid, question_text, answer_kind, mandatory, question_order
    """
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(
            sql_text(
                """
                SELECT question_id, external_qid, question_text, answer_type, mandatory, question_order
                FROM questionnaire_question
                WHERE screen_key = :skey
                ORDER BY question_order ASC, question_id ASC
                """
            ),
            {"skey": screen_key},
        ).fetchall()

    seen: set[str] = set()
    out: List[Dict[str, Any]] = []
    for row in rows:
        qid = str(row[0])
        if qid in seen:
            continue
        seen.add(qid)
        out.append(
            {
                "question_id": qid,
                "external_qid": row[1],
                "question_text": row[2],
                "answer_kind": row[3],
                "mandatory": bool(row[4]),
                "question_order": int(row[5]),
            }
        )
    return out


def count_responses_for_screen(response_set_id: str, screen_key: str) -> int:
    """Return the number of responses within a screen for a response set."""
    eng = get_engine()
    with eng.connect() as conn:
        count = conn.execute(
            sql_text(
                """
                SELECT COUNT(*)
                FROM response r
                WHERE r.response_set_id = :rs
                  AND r.question_id IN (
                      SELECT q.question_id FROM questionnaire_question q WHERE q.screen_key = :skey
                  )
                """
            ),
            {"rs": response_set_id, "skey": screen_key},
        ).scalar_one()
    return int(count)
