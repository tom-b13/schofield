"""Question-related repository helpers for authoring.

Encapsulates DB reads/writes used by authoring routes, keeping HTTP layer
free of direct SQL and enforcing error-handling conventions from AGENTS.md.
"""

from __future__ import annotations

import logging
from sqlalchemy import text as sql_text

from app.db.base import get_engine

logger = logging.getLogger(__name__)


def get_next_question_order(screen_key: str) -> int:
    """Return the next contiguous question_order value for a screen.

    Attempts MAX(question_order) first; on error or no rows, falls back to
    COUNT(*) + 1. Logs errors at ERROR with exc_info, never fails silently.
    """
    eng = get_engine()
    # Primary path: use MAX(question_order)
    try:
        with eng.connect() as conn:
            row = conn.execute(
                sql_text(
                    "SELECT COALESCE(MAX(question_order), 0) FROM questionnaire_question WHERE screen_key = :sid"
                ),
                {"sid": str(screen_key)},
            ).fetchone()
            base = int(row[0]) if row and row[0] is not None else 0
            return base + 1
    except Exception:
        logger.error(
            "get_next_question_order MAX failed for screen_key=%s", screen_key, exc_info=True
        )

    # Fallback: COUNT(*) + 1
    try:
        with eng.connect() as conn2:
            row2 = conn2.execute(
                sql_text("SELECT COUNT(*) FROM questionnaire_question WHERE screen_key = :sid"),
                {"sid": str(screen_key)},
            ).fetchone()
            cnt = int(row2[0]) if row2 and row2[0] is not None else 0
            return cnt + 1
    except Exception:
        logger.error(
            "get_next_question_order COUNT fallback failed for screen_key=%s",
            screen_key,
            exc_info=True,
        )
        return 1


def move_question_to_screen(question_id: str, target_screen_key: str) -> None:
    """Move a question to a different screen by updating its screen_key.

    Executes in its own transaction. Logs failures before re-raising to let
    callers decide recovery (e.g., reindex on source screen).
    """
    eng = get_engine()
    try:
        with eng.begin() as conn:
            conn.execute(
                sql_text(
                    "UPDATE questionnaire_question SET screen_key = :tgt WHERE question_id = :qid"
                ),
                {"tgt": str(target_screen_key), "qid": str(question_id)},
            )
    except Exception:
        logger.error(
            "move_question_to_screen failed qid=%s target_screen=%s",
            question_id,
            target_screen_key,
            exc_info=True,
        )
        raise

