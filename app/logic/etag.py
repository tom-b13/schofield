"""ETag computation helpers.

Provides reusable functions to compute weak ETags for screen resources
based on latest answer state. Centralizes logic to satisfy DRY per AGENTS.md.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import text as sql_text

from app.db.base import get_engine


def compute_screen_etag(response_set_id: str, screen_key: str) -> str:
    """Compute a weak ETag for a screen within a response set based on latest answers.

    Uses max(answered_at) and row count for the screen's questions to produce a stable token.
    """
    eng = get_engine()
    with eng.connect() as conn:
        max_row = conn.execute(
            sql_text(
                """
                SELECT MAX(answered_at) AS max_ts, COUNT(*) AS cnt
                FROM response r
                WHERE r.response_set_id = :rs
                  AND r.question_id IN (
                      SELECT q.question_id FROM questionnaire_question q WHERE q.screen_key = :skey
                  )
                """
            ),
            {"rs": response_set_id, "skey": screen_key},
        ).mappings().one_or_none()
    max_ts = str((max_row or {}).get("max_ts") or "0")
    cnt = int((max_row or {}).get("cnt") or 0)
    token = f"{response_set_id}:{screen_key}:{max_ts}:{cnt}".encode("utf-8")
    digest = hashlib.sha1(token).hexdigest()
    return f'W/"{digest}"'

