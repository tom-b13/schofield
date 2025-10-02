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


def get_visibility_rules_for_screen(screen_key: str) -> dict[str, tuple[str | None, list | None]]:
    """Return visibility metadata for all questions on a screen.

    For each question_id on the given screen_key, return a tuple of
    (parent_question_id, visible_if_value_list_or_none).

    - Base questions (no parent) map to (None, None)
    - Child questions include their parent's UUID and a list of string values
      that should make the child visible when equal to the parent's canonical
      answer value.
    """
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(
            sql_text(
                """
                SELECT question_id, parent_question_id, visible_if_value
                FROM questionnaire_question
                WHERE screen_key = :skey
                """
            ),
            {"skey": screen_key},
        ).fetchall()

    def _to_list(val: Any) -> list | None:
        if val is None:
            return None
        s = str(val).strip()
        if not s:
            return None
        # Accept JSON array in text if present, else a single value
        try:
            import json

            parsed = json.loads(s)
            if isinstance(parsed, list):
                return [str(x) for x in parsed]
        except Exception:
            pass
        return [s]

    out: dict[str, tuple[str | None, list | None]] = {}
    for row in rows:
        qid = str(row[0])
        parent_qid = str(row[1]) if row[1] is not None else None
        vis_list = _to_list(row[2])
        out[qid] = (parent_qid, vis_list)
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
