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
    """Move a question to a different screen by updating both identifiers.

    Resolves the target `screen_id` from the provided `target_screen_key` and
    atomically updates both `screen_id` and `screen_key` for the question. The
    transaction is committed before any caller-triggered reindexing to avoid
    unique collisions on (screen_id, question_order) during source reindex.
    """
    eng = get_engine()
    try:
        with eng.begin() as conn:
            # Resolve target screen UUID first (authoritative linkage)
            row = conn.execute(
                sql_text("SELECT screen_id FROM screen WHERE screen_key = :skey"),
                {"skey": str(target_screen_key)},
            ).fetchone()
            target_screen_id = str(row[0]) if row and row[0] is not None else None
            # Proceed with update; rely on the foreign key to enforce existence
            conn.execute(
                sql_text(
                    "UPDATE questionnaire_question SET screen_id = :sid, screen_key = :skey WHERE question_id = :qid"
                ),
                {"sid": target_screen_id, "skey": str(target_screen_key), "qid": str(question_id)},
            )
            # Exiting the context commits before any subsequent reindex
    except Exception:
        logger.error(
            "move_question_to_screen failed qid=%s target_screen=%s",
            question_id,
            target_screen_key,
            exc_info=True,
        )
        raise


def update_question_text(question_id: str, new_text: str) -> None:
    """Update a question's text by `question_id` in its own transaction.

    Logs failures and re-raises to let callers decide the recovery path.
    """
    eng = get_engine()
    try:
        with eng.begin() as conn:
            conn.execute(
                sql_text("UPDATE questionnaire_question SET question_text = :t WHERE question_id = :qid"),
                {"t": str(new_text).strip(), "qid": str(question_id)},
            )
    except Exception:
        logger.error(
            "update_question_text failed qid=%s", question_id, exc_info=True
        )
        raise


def create_question(*, screen_id: str, question_text: str, order_value: int) -> dict:
    """Insert a question row and return identifiers.

    - Resolves the UUID `screen_id` for the provided token (UUID or screen_key)
      and sets both `screen_id` and `screen_key` columns.
    - Sets `answer_kind` to a non-null default ('short_string') to satisfy
      NOT NULL constraints while routes may still return `answer_kind=null`.
    Returns a mapping containing `question_id` and `external_qid`.
    """
    import uuid
    from uuid import UUID

    eng = get_engine()
    new_qid = str(uuid.uuid4())

    # Resolve screen identifiers from the provided token
    provided_token = str(screen_id)
    resolved_screen_id: str | None = None
    resolved_screen_key: str | None = None
    with eng.connect() as conn:
        is_uuid = False
        try:
            UUID(provided_token)
            is_uuid = True
        except Exception:
            is_uuid = False
        if is_uuid:
            row = conn.execute(
                sql_text("SELECT screen_key FROM screen WHERE screen_id = :sid"),
                {"sid": provided_token},
            ).fetchone()
            resolved_screen_id = provided_token
            resolved_screen_key = str(row[0]) if row and row[0] is not None else None
        else:
            row = conn.execute(
                sql_text("SELECT screen_id FROM screen WHERE screen_key = :skey"),
                {"skey": provided_token},
            ).fetchone()
            resolved_screen_id = str(row[0]) if row and row[0] is not None else None
            resolved_screen_key = provided_token

    try:
        with eng.begin() as w1:
            w1.execute(
                sql_text(
                    """
                    INSERT INTO questionnaire_question (
                        question_id, screen_id, screen_key, external_qid, question_order, question_text, answer_kind, mandatory
                    )
                    VALUES (:qid, :sid, :skey, :ext, :ord, :qtext, :atype, FALSE)
                    """
                ),
                {
                    "qid": new_qid,
                    "sid": resolved_screen_id,
                    "skey": resolved_screen_key,
                    "ext": new_qid,
                    "ord": int(order_value),
                    "qtext": question_text,
                    "atype": "short_string",
                },
            )
    except Exception:
        logger.error(
            "create_question insert failed qid=%s screen_token=%s",
            new_qid,
            provided_token,
            exc_info=True,
        )
        raise
    return {"question_id": new_qid, "external_qid": new_qid}


def get_question_metadata(question_id: str) -> dict | None:
    """Return question metadata: screen_key, question_text, question_order (int).

    Provides a fallback path when `question_order` is unavailable in schema.
    """
    eng = get_engine()
    # Preferred path including question_order
    try:
        with eng.connect() as conn:
            row = conn.execute(
                sql_text(
                    "SELECT screen_key, question_text, COALESCE(question_order, 0) FROM questionnaire_question WHERE question_id = :qid"
                ),
                {"qid": question_id},
            ).fetchone()
        if row:
            return {
                "screen_key": str(row[0]),
                "question_text": str(row[1]),
                "question_order": int(row[2]) if row[2] is not None else 0,
            }
    except Exception:
        logger.error("get_question_metadata primary select failed qid=%s", question_id, exc_info=True)

    # Fallback without question_order
    with eng.connect() as conn2:
        row2 = conn2.execute(
            sql_text("SELECT screen_key, question_text FROM questionnaire_question WHERE question_id = :qid"),
            {"qid": question_id},
        ).fetchone()
    if not row2:
        return None
    return {"screen_key": str(row2[0]), "question_text": str(row2[1]), "question_order": 0}


def get_external_qid(question_id: str) -> str | None:
    """Return the external_qid for a question, or None when unavailable."""
    eng = get_engine()
    try:
        with eng.connect() as conn:
            row = conn.execute(
                sql_text("SELECT external_qid FROM questionnaire_question WHERE question_id = :qid"),
                {"qid": question_id},
            ).fetchone()
            if row and row[0] is not None:
                return str(row[0])
    except Exception:
        logger.error("get_external_qid select failed qid=%s", question_id, exc_info=True)
    return None


def update_question_visibility(*, question_id: str, parent_qid: str | None, visible_if_values: list[str] | None) -> None:
    """Update parent_question_id and visible_if_value for a question.

    Uses explicit parameter binding and safe JSONB casting. When
    `visible_if_values` is None, sets the column to NULL; otherwise binds the
    JSON text and casts it using CAST(:vis AS JSONB).
    """
    eng = get_engine()
    import json as _json
    try:
        with eng.begin() as conn:
            if visible_if_values is None:
                conn.execute(
                    sql_text(
                        "UPDATE questionnaire_question SET parent_question_id = :pid, visible_if_value = NULL WHERE question_id = :qid"
                    ),
                    {"pid": parent_qid, "qid": question_id},
                )
            else:
                vis_param = _json.dumps(visible_if_values)
                conn.execute(
                    sql_text(
                        "UPDATE questionnaire_question SET parent_question_id = :pid, visible_if_value = CAST(:vis AS JSONB) WHERE question_id = :qid"
                    ),
                    {"pid": parent_qid, "vis": vis_param, "qid": question_id},
                )
    except Exception:
        logger.error(
            "update_question_visibility failed qid=%s parent=%s vis=%s",
            question_id,
            parent_qid,
            visible_if_values,
            exc_info=True,
        )
        raise


def get_question_text_and_order(question_id: str) -> tuple[str, int] | None:
    """Return (question_text, question_order) for a question.

    Provides a fallback path when `question_order` is unavailable; in that case,
    returns (question_text, 0). Logs errors and avoids leaking SQL to callers.
    """
    eng = get_engine()
    try:
        with eng.connect() as conn:
            row = conn.execute(
                sql_text(
                    "SELECT question_text, COALESCE(question_order, 0) FROM questionnaire_question WHERE question_id = :qid"
                ),
                {"qid": question_id},
            ).fetchone()
        if row:
            txt = str(row[0]) if row[0] is not None else ""
            ord_val = int(row[1]) if row[1] is not None else 0
            return txt, ord_val
    except Exception:
        logger.error(
            "get_question_text_and_order primary select failed qid=%s",
            question_id,
            exc_info=True,
        )
    # Fallback: select only question_text
    try:
        with eng.connect() as conn2:
            row2 = conn2.execute(
                sql_text("SELECT question_text FROM questionnaire_question WHERE question_id = :qid"),
                {"qid": question_id},
            ).fetchone()
        if row2:
            return (str(row2[0]) if row2[0] is not None else "", 0)
    except Exception:
        logger.error(
            "get_question_text_and_order fallback select failed qid=%s",
            question_id,
            exc_info=True,
        )
    return None


def resolve_question_identifier(token: str) -> str | None:
    """Resolve an arbitrary token to an internal question_id.

    Accepts either a native `question_id` or an `external_qid`. Returns the
    canonical `question_id` string or None if not found.
    """
    eng = get_engine()
    try:
        with eng.connect() as conn:
            row = conn.execute(
                sql_text(
                    "SELECT question_id FROM questionnaire_question WHERE external_qid = :tok OR question_id = :tok LIMIT 1"
                ),
                {"tok": str(token)},
            ).fetchone()
            if row and row[0] is not None:
                return str(row[0])
    except Exception:
        logger.error(
            "resolve_question_identifier failed token=%s",
            token,
            exc_info=True,
        )
    return None


def is_parent_cycle(question_id: str, parent_qid: str) -> bool:
    """Return True if setting `parent_qid` would create a two-node cycle.

    Detects self-parenting and the case where the parent already points back
    to the child. Uses read-only queries and logs errors.
    """
    if str(question_id) == str(parent_qid):
        return True
    eng = get_engine()
    try:
        with eng.connect() as conn:
            row = conn.execute(
                sql_text(
                    "SELECT parent_question_id FROM questionnaire_question WHERE question_id = :pid"
                ),
                {"pid": parent_qid},
            ).fetchone()
        return bool(row and row[0] is not None and str(row[0]) == str(question_id))
    except Exception:
        logger.error(
            "is_parent_cycle read failed child=%s parent=%s",
            question_id,
            parent_qid,
            exc_info=True,
        )
        return False
