"""Screen-related data access helpers.

These functions encapsulate SQL queries for screen metadata, questions,
and response counts to keep route handlers free of persistence details.
"""

from __future__ import annotations

from typing import Any, Dict, List
import logging
import sys
from uuid import UUID
import json

from sqlalchemy import text as sql_text
from sqlalchemy.exc import ProgrammingError

from app.db.base import get_engine

logger = logging.getLogger(__name__)


def get_screen_metadata(screen_id: str) -> tuple[str, str] | None:
    """Return (screen_key, title) for a given screen identifier.

    Accepts either a UUID `screen_id` or a non-UUID `screen_key` token.
    When a UUID-like token is provided, lookup by `screen_id`; otherwise
    lookup by `screen_key`. Returns (screen_key, title) or None if missing.
    """
    # Detect UUID tokens; fall back to treating the value as a screen_key
    is_uuid = False
    try:
        UUID(str(screen_id))
        is_uuid = True
    except Exception:
        is_uuid = False

    eng = get_engine()
    with eng.connect() as conn:
        if is_uuid:
            row = conn.execute(
                sql_text("SELECT screen_key, title FROM screens WHERE screen_id = :sid"),
                {"sid": screen_id},
            ).fetchone()
        else:
            row = conn.execute(
                sql_text("SELECT screen_key, title FROM screens WHERE screen_key = :skey"),
                {"skey": screen_id},
            ).fetchone()
    if not row:
        return None
    return str(row[0]), str(row[1])


def get_screen_id_for_key(screen_key: str) -> str | None:
    """Return the UUID screen_id for a given screen_key, or None if missing.

    This helper is used by GET screen route to populate the 'screen' alias
    object when the path token is a non-UUID key.
    """
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            sql_text("SELECT screen_id FROM screens WHERE screen_key = :skey"),
            {"skey": screen_key},
        ).fetchone()
    if not row:
        return None
    return str(row[0])


def get_screen_by_key(screen_key: str) -> dict | None:
    """Return a mapping for a screen identified by `screen_key`.

    The returned dict includes at minimum `screen_id` and `screen_key`. When
    available, it also includes a `questions` key listing question rows for
    this screen, using the same shape as `list_questions_for_screen`.
    """
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            sql_text("SELECT screen_id, screen_key FROM screens WHERE screen_key = :skey"),
            {"skey": screen_key},
        ).fetchone()
    if not row:
        return None
    # Best-effort questions list; failures should not break the basic mapping
    try:
        questions = list_questions_for_screen(screen_key)
    except Exception:
        questions = []
    return {"screen_id": str(row[0]), "screen_key": str(row[1]), "questions": questions}


def get_screen_key_for_question(question_id: str) -> str | None:
    """Return the screen_key for a given question_id, or None if missing.

    Deterministically resolves the parent screen for a question to align
    PATCH ETag computation with the GET screen view.
    """
    eng = get_engine()
    try:
        with eng.connect() as conn:
            row = conn.execute(
                sql_text(
                    "SELECT screen_key FROM questionnaire_question WHERE question_id = :qid"
                ),
                {"qid": question_id},
            ).fetchone()
            # Fallback join on screens when screen_key is not directly available
            if not row or row[0] is None:
                row = conn.execute(
                    sql_text(
                        "SELECT s.screen_key FROM questionnaire_question q JOIN screens s ON q.screen_id = s.screen_id WHERE q.question_id = :qid"
                    ),
                    {"qid": question_id},
                ).fetchone()
    except ProgrammingError:
        # Schema variance: retry using JOIN against screens to resolve screen_key
        try:
            with eng.connect() as conn:
                row = conn.execute(
                    sql_text(
                        "SELECT s.screen_key FROM questionnaire_question q JOIN screens s ON q.screen_id = s.screen_id WHERE q.question_id = :qid"
                    ),
                    {"qid": question_id},
                ).fetchone()
        except Exception:
            row = None
    if not row:
        return None
    return str(row[0])


def list_questions_for_screen(screen_key: str) -> list[dict]:
    """List questions bound to a screen, ordered deterministically and deduplicated.

    Returns a list of dicts containing:
    - question_id, external_qid, question_text, answer_kind, mandatory, question_order
    """
    eng = get_engine()
    with eng.connect() as conn:
        # Support both schemas: direct screen_key column or FK via screens table
        try:
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
        except Exception:
            # Fallback: resolve via join on screens when questionnaire_question has screen_id only
            rows = conn.execute(
                sql_text(
                    """
                    SELECT q.question_id, q.external_qid, q.question_text, q.answer_type, q.mandatory, q.question_order
                    FROM questionnaire_question q
                    JOIN screens s ON q.screen_id = s.screen_id
                    WHERE s.screen_key = :skey
                    ORDER BY q.question_order ASC, q.question_id ASC
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


def get_screen_title_and_order(questionnaire_id: str, screen_key: str) -> tuple[str | None, int | None]:
    """Return (title, screen_order) for a screen within a questionnaire.

    Encapsulates reads needed by authoring routes and shields HTTP layer from SQL.
    On schema or read errors, logs at ERROR and attempts a minimal fallback that
    returns only title when available.
    """
    eng = get_engine()
    try:
        with eng.connect() as conn:
            row = conn.execute(
                sql_text(
                    "SELECT title, COALESCE(screen_order, 0) FROM screens WHERE questionnaire_id = :qid AND screen_key = :skey"
                ),
                {"qid": questionnaire_id, "skey": screen_key},
            ).fetchone()
        if row is None:
            return None, None
        title = str(row[0]) if row[0] is not None else None
        order_val = int(row[1]) if row[1] is not None else None
        return title, order_val
    except Exception:
        logger.error(
            "get_screen_title_and_order primary read failed qid=%s screen_key=%s",
            questionnaire_id,
            screen_key,
            exc_info=True,
        )
        # Fallback: try selecting title only
        try:
            with eng.connect() as conn2:
                row2 = conn2.execute(
                    sql_text(
                        "SELECT title FROM screens WHERE questionnaire_id = :qid AND screen_key = :skey"
                    ),
                    {"qid": questionnaire_id, "skey": screen_key},
                ).fetchone()
            if not row2:
                return None, None
            return (str(row2[0]) if row2[0] is not None else None), None
        except Exception:
            logger.error(
                "get_screen_title_and_order fallback read failed qid=%s screen_key=%s",
                questionnaire_id,
                screen_key,
                exc_info=True,
            )
            return None, None


def question_exists_on_screen(question_id: str) -> bool:
    """Return True if the given question_id exists in questionnaire_question.

    Used by routes to distinguish truly unknown questions from metadata lookup
    issues when deciding between 404 and proceeding with an upsert.
    """
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            sql_text("SELECT 1 FROM questionnaire_question WHERE question_id = :qid LIMIT 1"),
            {"qid": question_id},
        ).fetchone()
    return row is not None


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

    # Build a mapping of external_qid -> question_id for this screen to allow
    # resolving non-UUID parent_question_id tokens (e.g., external_qid like 'q_parent_bool').
    ext_to_qid: dict[str, str] = {}
    try:
        with eng.connect() as conn:
            ext_rows = conn.execute(
                sql_text(
                    """
                    SELECT external_qid, question_id
                    FROM questionnaire_question
                    WHERE screen_key = :skey
                    """
                ),
                {"skey": screen_key},
            ).fetchall()
        for er in ext_rows:
            ek = er[0]
            ev = er[1]
            if ek:
                try:
                    # Normalize external_qid keys to case-insensitive map with trimmed tokens
                    ext_to_qid[str(ek).strip().lower()] = str(ev)
                except Exception:
                    continue
    except Exception:
        # If mapping cannot be built, proceed without it; unresolved parents remain None
        ext_to_qid = {}

    def _to_list(val: Any) -> list | None:
        if val is None:
            return None
        # If the DB already returns a native list/array, normalize directly
        if isinstance(val, (list, tuple)):
            out_list: list[str] = []
            for x in val:
                if isinstance(x, bool):
                    out_list.append("true" if x else "false")
                else:
                    xs = str(x)
                    if xs.lower() in {"true", "false"}:
                        out_list.append(xs.lower())
                    else:
                        out_list.append(xs)
            return out_list
        s = str(val).strip()
        if not s:
            return None
        # Accept JSON array in text if present, else a single value
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                out: list[str] = []
                for x in parsed:
                    # Canonicalize booleans to 'true'/'false' strings
                    if isinstance(x, bool):
                        out.append("true" if x else "false")
                    else:
                        xs = str(x)
                        if xs.lower() in {"true", "false"}:
                            out.append(xs.lower())
                        else:
                            out.append(xs)
                return out
            # If JSON parses to a scalar, treat as single visible value
            if isinstance(parsed, (str, bool)):
                if isinstance(parsed, bool):
                    return ["true" if parsed else "false"]
                ps = str(parsed)
                return [ps.lower() if ps.lower() in {"true", "false"} else ps]
        except json.JSONDecodeError:
            logger.error(
                "visible_if JSON decode failed for screen_key=%s payload=%s",
                screen_key,
                s,
                exc_info=True,
            )
        # Single value path: canonicalize boolean-like tokens
        if s.lower() in {"true", "false"}:
            return [s.lower()]
        # Also handle literal Python boolean strings
        if s in {"True", "False"}:
            return [s.lower()]
        return [s]

    out: dict[str, tuple[str | None, list | None]] = {}
    for row in rows:
        qid = str(row[0])
        raw_parent = row[1]
        parent_qid: str | None
        if raw_parent is None:
            parent_qid = None
        else:
            candidate = str(raw_parent)
            # Coerce to UUID when possible; otherwise resolve via external_qid mapping
            try:
                UUID(candidate)
                parent_qid = candidate
            except Exception:
                # Not a UUID -> attempt resolution from external_qid on same screen
                candidate_norm = candidate.strip().lower()
                parent_qid = ext_to_qid.get(candidate_norm)
                # If still unresolved, perform a fallback lookup across all questionnaire_question
                # to avoid treating children as base-visible when the parent token is a non-UUID
                # external_qid defined on another screen.
                if not parent_qid:
                    try:
                        with eng.connect() as conn:
                            prow = conn.execute(
                                sql_text(
                                    "SELECT question_id FROM questionnaire_question WHERE external_qid = :ext LIMIT 1"
                                ),
                                {"ext": candidate},
                            ).fetchone()
                        if prow:
                            parent_qid = str(prow[0])
                    except Exception:
                        # Leave as None when not resolvable; caller will treat as base question
                        parent_qid = None
        vis_list = _to_list(row[2])
        if parent_qid:
            logger.info(
                "rules_parse screen_key=%s qid=%s parent=%s raw_visible_if=%s parsed=%s",
                screen_key,
                qid,
                parent_qid,
                row[2],
                vis_list,
            )
        out[qid] = (parent_qid, vis_list)
    return out


def get_screen_row_for_update(screen_key: str) -> dict | None:
    """Return screen metadata for update operations.

    Attempts to fetch (screen_id, screen_key, title, screen_order). If the
    schema lacks `screen_order`, falls back to fetching without it and returns
    `screen_order` as 0. Returns None when the screen does not exist.
    """
    eng = get_engine()
    # Preferred path including screen_order
    try:
        with eng.connect() as r1:
            row = r1.execute(
                sql_text(
                    "SELECT screen_id, screen_key, title, COALESCE(screen_order, 0) FROM screens WHERE screen_key = :skey"
                ),
                {"skey": screen_key},
            ).fetchone()
        if row:
            return {
                "screen_id": str(row[0]),
                "screen_key": str(row[1]),
                "title": str(row[2]),
                "screen_order": int(row[3]) if row[3] is not None else 0,
            }
    except Exception:
        logger.error(
            "get_screen_row_for_update primary select failed screen_key=%s",
            screen_key,
            exc_info=True,
        )
    # Fallback without screen_order
    with eng.connect() as r2:
        row2 = r2.execute(
            sql_text("SELECT screen_id, screen_key, title FROM screens WHERE screen_key = :skey"),
            {"skey": screen_key},
        ).fetchone()
    if not row2:
        return None
    return {
        "screen_id": str(row2[0]),
        "screen_key": str(row2[1]),
        "title": str(row2[2]),
        "screen_order": 0,
    }


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


def update_screen_title(screen_key: str, title: str) -> None:
    """Update a screen's title by `screen_key` in its own transaction.

    Single-purpose helper used by authoring routes to preserve separation of
    concerns. Logs and re-raises unexpected errors to avoid silent failure.
    """
    eng = get_engine()
    try:
        with eng.begin() as conn:
            conn.execute(
                sql_text("UPDATE screens SET title = :t WHERE screen_key = :skey"),
                {"t": str(title).strip(), "skey": str(screen_key)},
            )
    except Exception:
        logger.error(
            "update_screen_title failed screen_key=%s", screen_key, exc_info=True
        )
        # Preserve previous behavior by propagating so route can decide handling
        raise


def has_duplicate_title(questionnaire_id: str, title: str) -> bool:
    """Return True when a screen with the same title exists for the questionnaire.

    Performs a case-insensitive comparison in the database. No silent failures.
    """
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            sql_text(
                "SELECT 1 FROM screens WHERE questionnaire_id = :qid AND LOWER(title) = LOWER(:t) LIMIT 1"
            ),
            {"qid": questionnaire_id, "t": title},
        ).fetchone()
    return row is not None


def create_screen(*, questionnaire_id: str, title: str, order_value: int) -> dict:
    """Insert a screen row and return identifiers.

    Attempts primary insert including `screen_order`; on failure, logs at
    ERROR and retries a fallback insert without `screen_order`. Returns a
    mapping containing `screen_id` and `screen_key`.
    """
    import uuid

    eng = get_engine()
    new_sid = str(uuid.uuid4())
    screen_key = new_sid
    try:
        with eng.begin() as conn_ins:
            conn_ins.execute(
                sql_text(
                    "INSERT INTO screens (screen_id, questionnaire_id, screen_key, title, screen_order) VALUES (:sid, :qid, :skey, :title, :ord)"
                ),
                {"sid": new_sid, "qid": questionnaire_id, "skey": screen_key, "title": title, "ord": int(order_value)},
            )
    except Exception:
        logger.error(
            "create_screen primary insert failed; attempting fallback sid=%s qid=%s",
            new_sid,
            questionnaire_id,
            exc_info=True,
        )
        with eng.begin() as conn_fb:
            conn_fb.execute(
                sql_text(
                    "INSERT INTO screens (screen_id, questionnaire_id, screen_key, title) VALUES (:sid, :qid, :skey, :title)"
                ),
                {"sid": new_sid, "qid": questionnaire_id, "skey": screen_key, "title": title},
            )
    return {"screen_id": new_sid, "screen_key": screen_key}


def get_questionnaire_id_for_screen(screen_key: str) -> str | None:
    """Return the questionnaire_id that owns the given screen_key, or None.

    Keeps route layer free of SQL by centralizing this lookup.
    """
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(
            sql_text("SELECT questionnaire_id FROM screens WHERE screen_key = :sid"),
            {"sid": screen_key},
        ).fetchone()
    if row and row[0] is not None:
        return str(row[0])
    return None
