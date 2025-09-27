"""Answer-related data access helpers.

Encapsulates queries and writes for autosave routes.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text as sql_text

from app.db.base import get_engine
import json
import uuid


def get_screen_key_for_question(question_id: str) -> str | None:
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            sql_text("SELECT screen_key FROM questionnaire_question WHERE question_id = :qid"),
            {"qid": question_id},
        ).fetchone()
    return str(row[0]) if row else None


def get_answer_kind_for_question(question_id: str) -> str | None:
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            sql_text("SELECT answer_type FROM questionnaire_question WHERE question_id = :qid"),
            {"qid": question_id},
        ).fetchone()
    return str(row[0]) if row else None


def get_existing_answer(response_set_id: str, question_id: str) -> tuple | None:
    """Return a tuple (option_id, value_text, value_number, value_bool) if present."""
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            sql_text(
                """
                SELECT option_id, value_text, value_number, value_bool
                FROM response
                WHERE response_set_id = :rs AND question_id = :qid
                """
            ),
            {"rs": response_set_id, "qid": question_id},
        ).fetchone()
    return tuple(row) if row is not None else None


def upsert_answer(
    response_set_id: str,
    question_id: str,
    option_id: str | None,
    value: Any,
    idempotency_key: str | None,
) -> None:
    """Insert or update an answer row for the (response_set, question).

    Uses a deterministic UUID5 based on response_set, question, and idempotency key
    to ensure idempotency across retries.
    """
    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(
            sql_text(
                """
                INSERT INTO response (response_id, response_set_id, question_id, option_id, value_text, value_number, value_bool, value_json, answered_at)
                VALUES (:rid, :rs, :qid, :opt, :vtext, :vnum, :vbool, CAST(:vjson AS JSONB), now())
                ON CONFLICT (response_set_id, question_id)
                DO UPDATE SET option_id = EXCLUDED.option_id,
                              value_text = EXCLUDED.value_text,
                              value_number = EXCLUDED.value_number,
                              value_bool = EXCLUDED.value_bool,
                              value_json = EXCLUDED.value_json,
                              answered_at = now()
                """
            ),
            {
                "rid": str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"epic-b:{response_set_id}:{question_id}:{idempotency_key or ''}",
                    )
                ),
                "rs": response_set_id,
                "qid": question_id,
                "opt": option_id,
                "vtext": value if isinstance(value, str) else None,
                "vnum": float(value) if isinstance(value, (int, float)) else None,
                "vbool": bool(value) if isinstance(value, bool) else None,
                "vjson": json.dumps(value) if value is not None else "null",
            },
        )

def response_id_exists(response_id: str) -> bool:
    """Return True if a response with the given response_id exists."""
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            sql_text("SELECT 1 FROM response WHERE response_id = :rid"),
            {"rid": response_id},
        ).fetchone()
    return row is not None
