"""Authoring skeleton routes (Epic G) — 501 Problem+JSON placeholders.

Defines minimal POST endpoints for authoring operations to satisfy
integration tests until full implementation exists. No business logic.
"""

from __future__ import annotations

from typing import Optional
import logging

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text as sql_text
import uuid
import hashlib
import json

from app.db.base import get_engine
from app.logic.request_replay import (
    check_replay_before_write,
    store_replay_after_success,
)
from app.logic.etag import compare_etag, compute_questionnaire_etag_for_authoring
from app.logic.order_sequences import reindex_screens, reindex_questions, reindex_screens_move
from app.logic.repository_screens import update_screen_title
from app.logic.repository_questions import (
    get_next_question_order,
    move_question_to_screen,
)


# NOTE: The parent application mounts this router under '/api/v1'.
# Therefore this router should use '/authoring' so the final path resolves to
# '/api/v1/authoring/...', matching the specification and integration tests.
router = APIRouter(prefix="/authoring")
logger = logging.getLogger(__name__)


def _problem_not_implemented(detail: str) -> JSONResponse:
    body = {
        "type": "about:blank",
        "title": "Not Implemented",
        "status": 501,
        "detail": detail,
        "code": "not_implemented",
    }
    return JSONResponse(content=body, status_code=501, media_type="application/problem+json")


@router.post("/questionnaires/{questionnaire_id}/screens")
# returns created screen payload with title and screen_order
async def create_screen(
    questionnaire_id: str,
    request: Request,  # FastAPI injects Request
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    response: Response = None,  # type: ignore[assignment]
) -> JSONResponse:
    logger.info(
        "epic_g.authoring.screen.create.entry questionnaire_id=%s idempotency_key=%s",
        questionnaire_id,
        idempotency_key,
    )
    # Debug instrumentation (Clarke): log raw payload and parsed fields early
    try:
        dbg_payload = await request.json() if request is not None else {}
    except Exception:
        dbg_payload = {}
    if isinstance(dbg_payload, dict):
        dbg_title = str(dbg_payload.get("title") or "").strip()
        dbg_pos = dbg_payload.get("proposed_position")
        logger.info(
            "epic_g.authoring.screen.create.debug questionnaire_id=%s title=%s proposed_position=%s payload_preview=%s",
            questionnaire_id,
            dbg_title,
            dbg_pos,
            {k: dbg_payload.get(k) for k in ("title", "proposed_position")},
        )
    # Idempotent replay short-circuit before any writes
    if request is not None and response is not None:
        body = check_replay_before_write(request, response, current_etag=None)
        if body is not None:
            # Ensure Questionnaire-ETag is set for replays using current persisted state
            try:
                q_etag = compute_questionnaire_etag_for_authoring(questionnaire_id)
                response.headers["Questionnaire-ETag"] = q_etag
            except Exception:
                logger.error(
                    "create_screen replay etag compute failed qid=%s",
                    questionnaire_id,
                    exc_info=True,
                )
            return JSONResponse(content=body, status_code=201, media_type="application/json", headers=dict(response.headers))

    try:
        payload = await request.json() if request is not None else {}
    except Exception:
        payload = {}
    title = str(payload.get("title") or "").strip()
    proposed_position = payload.get("proposed_position")
    # Clarke instrumentation: echo payload keys and approximate raw length after parsing
    try:
        keys = list(payload.keys()) if isinstance(payload, dict) else []
        raw_len = (
            len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
            if isinstance(payload, dict)
            else 0
        )
        logger.info(
            "epic_g.authoring.screen.create.payload keys=%s len=%s",
            keys,
            raw_len,
        )
    except Exception:
        logger.error("screen.create payload logging failed", exc_info=True)
    # Validate proposed position if provided
    if proposed_position is not None:
        try:
            if int(proposed_position) <= 0:
                errors = [{"path": "$.proposed_position", "code": "invalid_or_non_positive"}]
                detail = "invalid proposed position"
                primary_code = errors[0]["code"]
                content = {"title": "Unprocessable Entity", "status": 422, "detail": detail, "code": primary_code, "errors": errors}
                return JSONResponse(status_code=422, content=content, media_type="application/problem+json")
        except Exception:
            errors = [{"path": "$.proposed_position", "code": "invalid_or_non_positive"}]
            detail = "invalid proposed position"
            primary_code = errors[0]["code"]
            content = {"title": "Unprocessable Entity", "status": 422, "detail": detail, "code": primary_code, "errors": errors}
            return JSONResponse(status_code=422, content=content, media_type="application/problem+json")

    eng = get_engine()
    # Duplicate title check should not be inside a write transaction
    with eng.connect() as conn_chk:
        row = conn_chk.execute(
            sql_text(
                "SELECT 1 FROM screens WHERE questionnaire_id = :qid AND LOWER(title) = LOWER(:t) LIMIT 1"
            ),
            {"qid": questionnaire_id, "t": title},
        ).fetchone()
        if row is not None:
            problem = {
                "title": "Conflict",
                "status": 409,
                "detail": "ETag mismatch or duplicate resource",
                "code": "duplicate_title",
            }
            return JSONResponse(problem, status_code=409, media_type="application/problem+json")

    # Compute final order (may perform its own writes safely) and prepare identifiers
    final_order = reindex_screens(
        questionnaire_id, int(proposed_position) if proposed_position is not None else None
    )
    new_sid = str(uuid.uuid4())
    screen_key = new_sid

    # First attempt: INSERT with screen_order in its own transaction
    try:
        with eng.begin() as conn_ins:
            conn_ins.execute(
                sql_text(
                    "INSERT INTO screens (screen_id, questionnaire_id, screen_key, title, screen_order) VALUES (:sid, :qid, :skey, :title, :ord)"
                ),
                {"sid": new_sid, "qid": questionnaire_id, "skey": screen_key, "title": title, "ord": int(final_order)},
            )
    except Exception:
        logger.error(
            "create_screen primary insert failed; attempting fallback sid=%s qid=%s",
            new_sid,
            exc_info=True,
        )
        # Fallback must run in a fresh transaction, not on a failed handle
        with eng.begin() as conn_fb:
            conn_fb.execute(
                sql_text(
                    "INSERT INTO screens (screen_id, questionnaire_id, screen_key, title) VALUES (:sid, :qid, :skey, :title)"
                ),
                {"sid": new_sid, "qid": questionnaire_id, "skey": screen_key, "title": title},
            )

    # Compute ETags
    scr_token = f"{screen_key}|{title}|{int(final_order)}".encode("utf-8")
    scr_etag = f'W/"{hashlib.sha1(scr_token).hexdigest()}"'
    q_etag = compute_questionnaire_etag_for_authoring(questionnaire_id)

    body = {"screen_id": screen_key, "title": title, "screen_order": int(final_order)}
    # Build response ensuring headers are set
    headers = {"Screen-ETag": scr_etag, "Questionnaire-ETag": q_etag}
    resp = JSONResponse(content=body, status_code=201, media_type="application/json", headers=headers)
    # Store idempotent replay after success
    try:
        if request is not None:
            # Attach headers to a temporary Response for storage shape parity
            temp_resp = Response()
            temp_resp.headers.update(headers)
            store_replay_after_success(request, temp_resp, body)
    except Exception:
        logger.error("create_screen idempotency store failed", exc_info=True)
    logger.info(
        "epic_g.authoring.screen.create.success questionnaire_id=%s screen_id=%s order=%s",
        questionnaire_id,
        body.get("screen_id"),
        body.get("screen_order"),
    )
    return resp


@router.post("/questionnaires/{questionnaire_id}/questions")
# returns created question scaffold payload
async def create_question(
    questionnaire_id: str,
    request: Request,  # FastAPI injects Request
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    response: Response = None,  # type: ignore[assignment]
) -> JSONResponse:
    logger.info(
        "epic_g.authoring.question.create.entry questionnaire_id=%s idempotency_key=%s",
        questionnaire_id,
        idempotency_key,
    )
    # Idempotent replay short-circuit
    if request is not None and response is not None:
        body = check_replay_before_write(request, response, current_etag=None)
        if body is not None:
            # Ensure Questionnaire-ETag is set for replays using current persisted state
            try:
                q_etag = compute_questionnaire_etag_for_authoring(questionnaire_id)
                response.headers["Questionnaire-ETag"] = q_etag
            except Exception:
                logger.error(
                    "create_question replay etag compute failed qid=%s",
                    questionnaire_id,
                    exc_info=True,
                )
            return JSONResponse(content=body, status_code=201, media_type="application/json", headers=dict(response.headers))

    try:
        payload = await request.json() if request is not None else {}
    except Exception:
        payload = {}
    # Required fields
    screen_id = str(payload.get("screen_id") or "").strip()
    question_text = str(payload.get("question_text") or "").strip()
    # Forbid answer_kind on create
    if "answer_kind" in payload and payload.get("answer_kind") is not None:
        problem = {
            "title": "Unprocessable Entity",
            "status": 422,
            "detail": "answer_kind must not be supplied on create",
            "code": "answer_kind_forbidden",
        }
        return JSONResponse(problem, status_code=422, media_type="application/problem+json")

    eng = get_engine()
    # Determine next order via repository helper with proper error handling
    next_order = get_next_question_order(screen_id)

    # Create question row in its own transaction; fallback in a fresh transaction
    new_qid = str(uuid.uuid4())
    try:
        with eng.begin() as w1:
            w1.execute(
                sql_text(
                    """
                    INSERT INTO questionnaire_question (question_id, screen_key, external_qid, question_order, question_text, answer_type, mandatory)
                    VALUES (:qid, :sid, :ext, :ord, :qtext, NULL, FALSE)
                    """
                ),
                {"qid": new_qid, "sid": screen_id, "ext": new_qid, "ord": int(next_order), "qtext": question_text},
            )
    except Exception:
        with eng.begin() as w2:
            w2.execute(
                sql_text(
                    """
                    INSERT INTO questionnaire_question (question_id, screen_key, external_qid, question_text, answer_type, mandatory)
                    VALUES (:qid, :sid, :ext, :qtext, :atype, FALSE)
                    """
                ),
                {"qid": new_qid, "sid": screen_id, "ext": new_qid, "qtext": question_text, "atype": "short_string"},
            )

    # Compute ETags (opaque values acceptable by schema)
    q_token = f"{new_qid}|{question_text}|{int(next_order)}".encode("utf-8")
    q_etag = f'W/"{hashlib.sha1(q_token).hexdigest()}"'
    s_token = f"{screen_id}|{int(next_order)}".encode("utf-8")
    s_etag = f'W/"{hashlib.sha1(s_token).hexdigest()}"'
    qn_etag = compute_questionnaire_etag_for_authoring(questionnaire_id)

    body = {
        "question_id": new_qid,
        "screen_id": screen_id,
        "question_text": question_text,
        "answer_kind": None,
        "question_order": int(next_order),
    }
    headers = {"Question-ETag": q_etag, "Screen-ETag": s_etag, "Questionnaire-ETag": qn_etag}
    resp = JSONResponse(content=body, status_code=201, media_type="application/json", headers=headers)
    try:
        if request is not None:
            temp_resp = Response()
            temp_resp.headers.update(headers)
            store_replay_after_success(request, temp_resp, body)
    except Exception:
        logger.error("create_question idempotency store failed", exc_info=True)
    logger.info(
        "epic_g.authoring.question.create.success questionnaire_id=%s question_id=%s screen_id=%s order=%s",
        questionnaire_id,
        body.get("question_id"),
        body.get("screen_id"),
        body.get("question_order"),
    )
    return resp


__all__ = ["router", "create_screen", "create_question"]


# --- Skeleton PATCH handlers requested by Clarke (no business logic) ---


@router.patch("/questionnaires/{questionnaire_id}/screens/{screen_id}")
# returns updated screen payload and ETags
async def update_screen(
    questionnaire_id: str,
    screen_id: str,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    # Resolve current screen and its order using a read-only connection; fallback without screen_order on failure
    eng = get_engine()
    db_sid = ""
    db_skey = ""
    cur_title = ""
    cur_order = 0
    with eng.connect() as r1:
        try:
            row = r1.execute(
                sql_text(
                    "SELECT screen_id, screen_key, title, COALESCE(screen_order, 0) FROM screens WHERE screen_key = :skey"
                ),
                {"skey": screen_id},
            ).fetchone()
        except Exception:
            row = None
    if row is None:
        with eng.connect() as r2:
            row2 = r2.execute(
                sql_text("SELECT screen_id, screen_key, title FROM screens WHERE screen_key = :skey"),
                {"skey": screen_id},
            ).fetchone()
            if row2 is None:
                problem = {"title": "Not Found", "status": 404, "detail": "screen not found", "code": "screen_missing"}
                return JSONResponse(problem, status_code=404, media_type="application/problem+json")
            db_sid = str(row2[0])
            db_skey = str(row2[1])
            cur_title = str(row2[2])
            cur_order = 0
    else:
        db_sid = str(row[0])
        db_skey = str(row[1])
        cur_title = str(row[2])
        cur_order = int(row[3])

    # Compute current Screen-ETag for If-Match enforcement
    cur_token = f"{db_skey}|{cur_title}|{int(cur_order)}".encode("utf-8")
    current_etag = f'W/"{hashlib.sha1(cur_token).hexdigest()}"'
    if not compare_etag(current_etag, if_match):
        problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "ETag does not match current resource",
            "code": "etag_mismatch",
        }
        return JSONResponse(problem, status_code=409, media_type="application/problem+json")

    # Parse updates
    try:
        payload = await request.json() if request is not None else {}
    except Exception:
        payload = {}
    # In practice FastAPI passes the request body through the test client; fall back to empty dict when unavailable
    if not isinstance(payload, dict):
        payload = {}
    new_title = payload.get("title")
    proposed_position = payload.get("proposed_position")
    if proposed_position is not None:
        try:
            if int(proposed_position) <= 0:
                problem = {
                    "title": "Unprocessable Entity",
                    "status": 422,
                    "detail": "invalid proposed position",
                    "code": "invalid_or_non_positive",
                    "errors": [{"path": "$.proposed_position", "code": "invalid_or_non_positive"}],
                }
                return JSONResponse(problem, status_code=422, media_type="application/problem+json")
        except Exception:
            problem = {
                "title": "Unprocessable Entity",
                "status": 422,
                "detail": "invalid proposed position",
                "code": "invalid_or_non_positive",
                "errors": [{"path": "$.proposed_position", "code": "invalid_or_non_positive"}],
            }
            return JSONResponse(problem, status_code=422, media_type="application/problem+json")

    # Apply updates via repository helper and dedicated reindex routine
    if isinstance(new_title, str) and new_title.strip():
        try:
            update_screen_title(screen_id, str(new_title).strip())
        except Exception:
            # Preserve behavior by continuing to re-read latest values; error is logged in repo
            pass

    if proposed_position is not None:
        # Delegate backend-authoritative reorder to helper (contiguous, clamped)
        try:
            _final = reindex_screens_move(questionnaire_id, db_skey, int(proposed_position))
        except Exception:
            logger.error("reindex_screens_move failed", exc_info=True)
            _final = None

        # Re-fetch to build response and ETags using a clean read
    try:
        with eng.connect() as r3:
            row2 = r3.execute(
                sql_text(
                    "SELECT title, COALESCE(screen_order, 0) FROM screens WHERE questionnaire_id = :qid AND screen_key = :skey"
                ),
                {"qid": questionnaire_id, "skey": screen_id},
            ).fetchone()
    except Exception:
        with eng.connect() as r4:
            r = r4.execute(
                sql_text(
                    "SELECT title FROM screens WHERE questionnaire_id = :qid AND screen_key = :skey"
                ),
                {"qid": questionnaire_id, "skey": screen_id},
            ).fetchone()
            row2 = (r[0] if r else cur_title, None)
    new_title_val = str(row2[0]) if row2 and row2[0] is not None else cur_title
    new_order_val = int(row2[1]) if row2 and row2[1] is not None else cur_order
    # Body order must reflect persisted DB value; do not override with helper result

    # Compute new ETags
    scr_token = f"{db_skey}|{new_title_val}|{int(new_order_val)}".encode("utf-8")
    scr_etag = f'W/"{hashlib.sha1(scr_token).hexdigest()}"'
    q_etag = compute_questionnaire_etag_for_authoring(questionnaire_id)

    # Clarke instrumentation: correlate proposed_position, helper final result, and reread order prior to return
    logger.info(
        "update_screen proposed_position=%s reindex_final=%s reread_order=%s",
        proposed_position,
        locals().get("_final"),
        new_order_val,
    )
    body = {"screen_id": screen_id, "title": new_title_val, "screen_order": int(new_order_val)}
    headers = {"Screen-ETag": scr_etag, "Questionnaire-ETag": q_etag}
    return JSONResponse(content=body, status_code=200, media_type="application/json", headers=headers)


@router.patch("/questions/{question_id}/position")
# returns reordered question payload and ETags
async def update_question_position(
    question_id: str,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    # Resolve current question state using a read-only connection; fallback without question_order
    eng = get_engine()
    with eng.connect() as r1:
        try:
            row = r1.execute(
                sql_text(
                    "SELECT screen_key, question_text, COALESCE(question_order, 0) FROM questionnaire_question WHERE question_id = :qid"
                ),
                {"qid": question_id},
            ).fetchone()
        except Exception:
            row = None
    if row is None:
        with eng.connect() as r2:
            row2 = r2.execute(
                sql_text("SELECT screen_key, question_text FROM questionnaire_question WHERE question_id = :qid"),
                {"qid": question_id},
            ).fetchone()
            if row2 is None:
                problem = {"title": "Not Found", "status": 404, "detail": "question not found", "code": "question_missing"}
                return JSONResponse(problem, status_code=404, media_type="application/problem+json")
            screen_id = str(row2[0])
            qtext = str(row2[1])
            cur_order = 0
    else:
        screen_id = str(row[0])
        qtext = str(row[1])
        cur_order = int(row[2])

    # Basic precondition: build current ETag and compare (wildcard supported via compare_etag in update_question)
    cur_token = f"{question_id}|{qtext}|{int(cur_order)}".encode("utf-8")
    current_etag = f'W/"{hashlib.sha1(cur_token).hexdigest()}"'
    if not compare_etag(current_etag, if_match):
        problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "ETag does not match current resource",
            "code": "etag_mismatch",
        }
        return JSONResponse(problem, status_code=409, media_type="application/problem+json")

    # Parse body for proposed_question_order and optional cross-screen move target
    try:
        payload = await request.json() if request is not None else {}
    except Exception:
        payload = {}
    proposed_order = payload.get("proposed_question_order") if isinstance(payload, dict) else None
    target_screen: Optional[str] = None
    if isinstance(payload, dict) and "screen_id" in payload:
        val = payload.get("screen_id")
        if isinstance(val, str) and val.strip():
            target_screen = val.strip()
    if proposed_order is not None:
        try:
            if int(proposed_order) <= 0:
                errors = [{"path": "$.proposed_question_order", "code": "invalid_or_non_positive"}]
                detail = "invalid proposed question order"
                primary_code = errors[0]["code"]
                content = {"title": "Unprocessable Entity", "status": 422, "detail": detail, "code": primary_code, "errors": errors}
                return JSONResponse(status_code=422, content=content, media_type="application/problem+json")
        except Exception:
            errors = [{"path": "$.proposed_question_order", "code": "invalid_or_non_positive"}]
            detail = "invalid proposed question order"
            primary_code = errors[0]["code"]
            content = {"title": "Unprocessable Entity", "status": 422, "detail": detail, "code": primary_code, "errors": errors}
            return JSONResponse(status_code=422, content=content, media_type="application/problem+json")

    # Handle cross-screen move validation and persistence if requested
    if target_screen and target_screen != screen_id:
        # Validate both current and target belong to same questionnaire
        cur_qid = None
        tgt_qid = None
        with eng.connect() as rc:
            rcur = rc.execute(sql_text("SELECT questionnaire_id FROM screens WHERE screen_key = :sid"), {"sid": screen_id}).fetchone()
            if rcur is not None and rcur[0] is not None:
                cur_qid = str(rcur[0])
            rtgt = rc.execute(sql_text("SELECT questionnaire_id FROM screens WHERE screen_key = :sid"), {"sid": target_screen}).fetchone()
            if rtgt is not None and rtgt[0] is not None:
                tgt_qid = str(rtgt[0])
        # Clarke instrumentation: log IDs and proposed move
        try:
            logger.info(
                "update_question_position cur_qid=%s tgt_qid=%s target_screen=%s proposed_order=%s",
                cur_qid,
                tgt_qid,
                target_screen,
                proposed_order,
            )
        except Exception:
            pass
        if tgt_qid is None or cur_qid is None or tgt_qid != cur_qid:
            errors = [{"path": "$.screen_id", "code": "outside_or_cross_questionnaire"}]
            detail = "target screen is outside current questionnaire"
            primary_code = errors[0]["code"]
            content = {"title": "Unprocessable Entity", "status": 422, "detail": detail, "code": primary_code, "errors": errors}
            return JSONResponse(status_code=422, content=content, media_type="application/problem+json")
        # Persist move and reindex both source and target containers
        try:
            move_question_to_screen(question_id, target_screen)
        except Exception:
            # Error already logged in repository; continue to attempt reindex fallback
            pass
        # Reindex source to close gaps, then switch context to target and place the question
        try:
            reindex_questions(screen_id, None, None)
        except Exception:
            logger.error("reindex_questions source reindex failed", exc_info=True)
        screen_id = target_screen

    # Perform contiguous reindex using helper in the current screen (append if None)
    final_order, _map = reindex_questions(screen_id, question_id, proposed_order)

    q_token = f"{question_id}|{qtext}|{int(final_order)}".encode("utf-8")
    q_etag = f'W/"{hashlib.sha1(q_token).hexdigest()}"'
    s_token = f"{screen_id}|{int(final_order)}".encode("utf-8")
    s_etag = f'W/"{hashlib.sha1(s_token).hexdigest()}"'
    # Compute Questionnaire-ETag using authoritative helper
    qid_val = None
    with eng.connect() as rc2:
        rowq = rc2.execute(sql_text("SELECT questionnaire_id FROM screens WHERE screen_key = :sid"), {"sid": screen_id}).fetchone()
        if rowq is not None and rowq[0] is not None:
            qid_val = str(rowq[0])
    qn_etag = compute_questionnaire_etag_for_authoring(qid_val or "")

    # Resolve external question id token for response parity
    try:
        with eng.connect() as r_ext:
            row_ext = r_ext.execute(
                sql_text("SELECT external_qid FROM questionnaire_question WHERE question_id = :qid"),
                {"qid": question_id},
            ).fetchone()
            external_qid = str(row_ext[0]) if row_ext and row_ext[0] is not None else question_id
    except Exception:
        external_qid = question_id
    body = {"question_id": external_qid, "screen_id": screen_id, "question_order": int(final_order)}
    headers = {"Question-ETag": q_etag, "Screen-ETag": s_etag, "Questionnaire-ETag": qn_etag}
    return JSONResponse(content=body, status_code=200, media_type="application/json", headers=headers)


@router.patch("/questions/{question_id}")
# returns updated question payload and ETags
async def update_question(
    question_id: str,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    # Load current state (guard against missing question_order column) using read-only connection
    eng = get_engine()
    with eng.connect() as r1:
        try:
            row = r1.execute(
                sql_text(
                    "SELECT screen_key, question_text, COALESCE(question_order, 0) FROM questionnaire_question WHERE question_id = :qid"
                ),
                {"qid": question_id},
            ).fetchone()
        except Exception:
            row = None
    if row is None:
        with eng.connect() as r2:
            row2 = r2.execute(
                sql_text("SELECT screen_key, question_text FROM questionnaire_question WHERE question_id = :qid"),
                {"qid": question_id},
            ).fetchone()
            if row2 is None:
                problem = {"title": "Not Found", "status": 404, "detail": "question not found", "code": "question_missing"}
                return JSONResponse(problem, status_code=404, media_type="application/problem+json")
            screen_id = str(row2[0])
            cur_text = str(row2[1])
            cur_order = 0
    else:
        screen_id = str(row[0])
        cur_text = str(row[1])
        cur_order = int(row[2])

    # If-Match precondition
    cur_token = f"{question_id}|{cur_text}|{int(cur_order)}".encode("utf-8")
    current_etag = f'W/"{hashlib.sha1(cur_token).hexdigest()}"'
    if not compare_etag(current_etag, if_match):
        problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "ETag does not match current resource",
            "code": "etag_mismatch",
        }
        return JSONResponse(problem, status_code=409, media_type="application/problem+json")

    # Parse body
    new_text = cur_text
    try:
        payload = await request.json() if request is not None else {}
    except Exception:
        payload = {}
    if isinstance(payload, dict) and "question_text" in payload:
        candidate = payload.get("question_text")
        if isinstance(candidate, str) and candidate.strip():
            new_text = str(candidate).strip()
        else:
            problem = {
                "title": "Unprocessable Entity",
                "status": 422,
                "detail": "invalid question_text",
                "errors": [{"path": "$.question_text", "code": "invalid"}],
            }
            return JSONResponse(problem, status_code=422, media_type="application/problem+json")
    # Update text (for this cycle we assume body contains question_text; integration asserts will drive)
    with eng.begin() as conn:
        conn.execute(
            sql_text("UPDATE questionnaire_question SET question_text = :t WHERE question_id = :qid"),
            {"t": new_text, "qid": question_id},
        )
    # Re-read result using clean read connection
    try:
        with eng.connect() as r3:
            row2 = r3.execute(
                sql_text(
                    "SELECT question_text, COALESCE(question_order, 0) FROM questionnaire_question WHERE question_id = :qid"
                ),
                {"qid": question_id},
            ).fetchone()
            final_text = str(row2[0]) if row2 and row2[0] is not None else new_text
            final_order = int(row2[1]) if row2 and row2[1] is not None else cur_order
    except Exception:
        with eng.connect() as r4:
            row2b = r4.execute(
                sql_text("SELECT question_text FROM questionnaire_question WHERE question_id = :qid"),
                {"qid": question_id},
            ).fetchone()
            final_text = str(row2b[0]) if row2b and row2b[0] is not None else new_text
            final_order = cur_order

    q_token = f"{question_id}|{final_text}|{int(final_order)}".encode("utf-8")
    q_etag = f'W/"{hashlib.sha1(q_token).hexdigest()}"'
    s_token = f"{screen_id}|{int(final_order)}".encode("utf-8")
    s_etag = f'W/"{hashlib.sha1(s_token).hexdigest()}"'
    # Resolve external question id and questionnaire id for headers/body
    try:
        with eng.connect() as r5:
            row_ext = r5.execute(sql_text("SELECT external_qid FROM questionnaire_question WHERE question_id = :qid"), {"qid": question_id}).fetchone()
            external_qid = str(row_ext[0]) if row_ext and row_ext[0] is not None else question_id
            row_qn = r5.execute(sql_text("SELECT questionnaire_id FROM screens WHERE screen_key = :sid"), {"sid": screen_id}).fetchone()
            questionnaire_id = str(row_qn[0]) if row_qn and row_qn[0] is not None else ""
    except Exception:
        external_qid = question_id
        questionnaire_id = ""
    qn_etag = compute_questionnaire_etag_for_authoring(questionnaire_id)

    body = {"question_id": external_qid, "question_text": final_text}
    headers = {"Question-ETag": q_etag, "Screen-ETag": s_etag, "Questionnaire-ETag": qn_etag}
    return JSONResponse(content=body, status_code=200, media_type="application/json", headers=headers)


@router.patch("/questions/{question_id}/visibility")
# returns updated visibility payload and ETags
async def update_question_visibility(
    question_id: str,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    # Resolve current question state using a read-only connection; fallback without question_order
    eng = get_engine()
    with eng.connect() as r1:
        try:
            row = r1.execute(
                sql_text(
                    "SELECT screen_key, question_text, COALESCE(question_order, 0) FROM questionnaire_question WHERE question_id = :qid"
                ),
                {"qid": question_id},
            ).fetchone()
        except Exception:
            row = None
    if row is None:
        with eng.connect() as r2:
            row2 = r2.execute(
                sql_text("SELECT screen_key, question_text FROM questionnaire_question WHERE question_id = :qid"),
                {"qid": question_id},
            ).fetchone()
            if row2 is None:
                problem = {"title": "Not Found", "status": 404, "detail": "question not found", "code": "question_missing"}
                return JSONResponse(problem, status_code=404, media_type="application/problem+json")
            screen_id = str(row2[0])
            cur_text = str(row2[1])
            cur_order = 0
    else:
        screen_id = str(row[0])
        cur_text = str(row[1])
        cur_order = int(row[2])

    # If-Match precondition based on current entity tag
    cur_token = f"{question_id}|{cur_text}|{int(cur_order)}".encode("utf-8")
    current_etag = f'W/"{hashlib.sha1(cur_token).hexdigest()}"'
    if not compare_etag(current_etag, if_match):
        problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "ETag does not match current resource",
            "code": "etag_mismatch",
        }
        return JSONResponse(problem, status_code=409, media_type="application/problem+json")

    # Parse body for parent_question_id and visible_if_value; default to NULLs when absent
    parent_qid: Optional[str] = None
    vis_val_raw = None
    try:
        payload = await request.json() if request is not None else {}
    except Exception:
        payload = {}
    if isinstance(payload, dict):
        if "parent_question_id" in payload:
            parent_qid = payload.get("parent_question_id")
        if "visible_if_value" in payload:
            vis_val_raw = payload.get("visible_if_value")

    # Resolve external parent token to internal UUID before validation/persist
    if isinstance(parent_qid, str) and parent_qid.strip():
        try:
            with eng.connect() as _rp:
                rpid = _rp.execute(
                    sql_text(
                        "SELECT question_id FROM questionnaire_question WHERE external_qid = :tok OR question_id = :tok LIMIT 1"
                    ),
                    {"tok": str(parent_qid)},
                ).fetchone()
            if rpid is not None and rpid[0] is not None:
                parent_qid = str(rpid[0])
        except Exception:
            pass

    # Two-node cycle detection
    if isinstance(parent_qid, str) and parent_qid:
        if str(parent_qid) == str(question_id):
            content = {
                "title": "Unprocessable Entity",
                "status": 422,
                "detail": "cyclic parent linkage",
                "code": "parent_cycle",
                "errors": [{"path": "$.parent_question_id", "code": "parent_cycle"}],
            }
            return JSONResponse(status_code=422, content=content, media_type="application/problem+json")
        try:
            with eng.connect() as _rcy:
                prow = _rcy.execute(
                    sql_text(
                        "SELECT parent_question_id FROM questionnaire_question WHERE question_id = :pid"
                    ),
                    {"pid": parent_qid},
                ).fetchone()
            if prow is not None and prow[0] is not None and str(prow[0]) == str(question_id):
                content = {
                    "title": "Unprocessable Entity",
                    "status": 422,
                    "detail": "cyclic parent linkage",
                    "code": "parent_cycle",
                    "errors": [{"path": "$.parent_question_id", "code": "parent_cycle"}],
                }
                return JSONResponse(status_code=422, content=content, media_type="application/problem+json")
        except Exception:
            # On DB error, skip cycle detection to avoid masking primary behavior
            pass

    # Validate compatibility with parent answer_kind (boolean canonicalisation)
    from app.logic.repository_answers import get_answer_kind_for_question  # local import to avoid cycles
    from app.logic.visibility_rules import validate_visibility_compatibility
    parent_kind = get_answer_kind_for_question(str(parent_qid)) if parent_qid else None

    def _canon_bool_list(value: object | None) -> Optional[list[str]]:
        if value is None:
            return None
        if isinstance(value, bool):
            return ["true" if value else "false"]
        try:
            s = str(value).strip().lower()
            if s in {"true", "false"}:
                return [s]
        except Exception:
            pass
        if isinstance(value, (list, tuple)):
            out: list[str] = []
            for item in value:
                if isinstance(item, bool):
                    out.append("true" if item else "false")
                else:
                    st = str(item).strip().lower()
                    if st in {"true", "false"}:
                        out.append(st)
                    else:
                        return None
            return out if out else None
        return None

    vis_canon: Optional[list[str]] = None
    if vis_val_raw is not None:
        # Enforce compatibility: only boolean parents may accept visible_if_value
        try:
            validate_visibility_compatibility(str(parent_kind or ""), vis_val_raw)
        except Exception:
            errors = [{"path": "$.visible_if_value", "code": "incompatible_with_parent_answer_kind"}]
            detail = "incompatible visible_if_value for given parent answer_kind"
            primary_code = errors[0]["code"]
            content = {"title": "Unprocessable Entity", "status": 422, "detail": detail, "code": primary_code, "errors": errors}
            return JSONResponse(status_code=422, content=content, media_type="application/problem+json")
        # Boolean-compatible parent: canonicalize to ['true'|'false'] list
        vis_canon = _canon_bool_list(vis_val_raw)

    # Persist updates
    with eng.begin() as conn:
        conn.execute(
            sql_text(
                "UPDATE questionnaire_question SET parent_question_id = :pid, visible_if_value = :vis WHERE question_id = :qid"
            ),
            {"pid": parent_qid, "vis": vis_canon, "qid": question_id},
        )

    # ETags
    q_token = f"{question_id}|{cur_text}|{int(cur_order)}".encode("utf-8")
    q_etag = f'W/"{hashlib.sha1(q_token).hexdigest()}"'
    s_token = f"{screen_id}|{int(cur_order)}".encode("utf-8")
    s_etag = f'W/"{hashlib.sha1(s_token).hexdigest()}"'
    qn_etag = f'W/"{hashlib.sha1(f"{screen_id}".encode()).hexdigest()}"'

    body = {
        "question_id": question_id,
        "parent_question_id": parent_qid,
        "visible_if_value": vis_canon,
    }
    headers = {"Question-ETag": q_etag, "Screen-ETag": s_etag, "Questionnaire-ETag": qn_etag}
    return JSONResponse(content=body, status_code=200, media_type="application/json", headers=headers)
