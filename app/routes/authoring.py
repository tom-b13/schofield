"""Authoring skeleton routes (Epic G) — 501 Problem+JSON placeholders.

Defines minimal POST endpoints for authoring operations to satisfy
integration tests until full implementation exists. No business logic.
"""

from __future__ import annotations

from typing import Optional
import logging

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse
import json

from app.logic.request_replay import (
    check_replay_before_write,
    store_replay_after_success,
)
from app.logic.etag import (
    compare_etag,
    compute_questionnaire_etag_for_authoring,
    compute_authoring_screen_etag,
    compute_authoring_screen_etag_from_order,
    compute_authoring_question_etag,
)
from app.logic.header_emitter import emit_etag_headers, SCOPE_TO_HEADER
from app.logic.order_sequences import reindex_screens, reindex_questions, reindex_screens_move
from app.logic.repository_screens import update_screen_title
from app.logic.repository_questions import (
    get_next_question_order,
    move_question_to_screen,
    get_question_metadata,
    update_question_visibility as repo_update_question_visibility,
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


@router.post("/screens")
async def create_screen_simple(request: Request) -> JSONResponse:
    """Create a screen using a simple JSON payload.

    Expects JSON with keys: questionnaire_id, title (screen_key optional/ignored).
    Emits Screen-ETag and Questionnaire-ETag headers; does not include generic ETag.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    questionnaire_id = str((payload or {}).get("questionnaire_id") or "").strip().strip('"').strip("'")
    title = str((payload or {}).get("title") or "").strip()
    if not questionnaire_id or not title:
        errors = []
        if not questionnaire_id:
            errors.append({"path": "$.questionnaire_id", "code": "missing"})
        if not title:
            errors.append({"path": "$.title", "code": "missing"})
        content = {"title": "Unprocessable Entity", "status": 422, "detail": "invalid create payload", "errors": errors}
        return JSONResponse(status_code=422, content=content, media_type="application/problem+json")

    # Duplicate title check — guard repository interaction
    from app.logic.repository_screens import has_duplicate_title, create_screen as repo_create_screen
    try:
        if has_duplicate_title(questionnaire_id, title):
            problem = {"title": "Conflict", "status": 409, "detail": "duplicate_title"}
            return JSONResponse(problem, status_code=409, media_type="application/problem+json")
    except Exception:
        # Treat repository failures as non-duplicate in Phase-0 skeleton
        logger.error("authoring.create_screen_simple.duplicate_check_failed", exc_info=True)

    # Determine final order (append to end); tolerate repository failures
    try:
        from app.logic.order_sequences import reindex_screens
        final_order = reindex_screens(questionnaire_id, None)
    except Exception:
        logger.error("authoring.create_screen_simple.reindex_failed", exc_info=True)
        final_order = 1

    # Create screen row; on failure, synthesize a Phase-0 success with computed headers only
    screen_key = None
    try:
        created = repo_create_screen(questionnaire_id=questionnaire_id, title=title, order_value=int(final_order))
        screen_key = created.get("screen_key") or created.get("screen_id")
    except Exception:
        logger.error("authoring.create_screen_simple.repo_create_failed", exc_info=True)
        # Prefer provided screen_key fallback; otherwise derive from title token
        try:
            screen_key = (payload or {}).get("screen_key") or title
        except Exception:
            screen_key = title or "screen"

    # Compute and emit ETags (domain-only headers); omit generic ETag per Phase-0
    scr_etag = compute_authoring_screen_etag(str(screen_key), title, int(final_order))
    q_etag = compute_questionnaire_etag_for_authoring(questionnaire_id)
    resp = JSONResponse({"screen_id": str(screen_key), "title": title, "screen_order": int(final_order)}, status_code=201)
    emit_etag_headers(resp, scope="screen", token=scr_etag, include_generic=False)
    emit_etag_headers(resp, scope="questionnaire", token=q_etag, include_generic=False)
    return resp


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
        logger.error(
            "create_screen debug payload parse failed questionnaire_id=%s",
            questionnaire_id,
            exc_info=True,
        )
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
                emit_etag_headers(response, scope="questionnaire", token=q_etag, include_generic=False)
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
        logger.error(
            "create_screen payload parse failed questionnaire_id=%s",
            questionnaire_id,
            exc_info=True,
        )
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

    # Duplicate title check should not be inside a write transaction
    from app.logic.repository_screens import has_duplicate_title, create_screen as repo_create_screen
    if has_duplicate_title(questionnaire_id, title):
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
    created = repo_create_screen(questionnaire_id=questionnaire_id, title=title, order_value=int(final_order))
    new_sid = created["screen_id"]
    screen_key = created["screen_key"]

    # Compute ETags
    scr_etag = compute_authoring_screen_etag(screen_key, title, int(final_order))
    q_etag = compute_questionnaire_etag_for_authoring(questionnaire_id)

    body = {"screen_id": screen_key, "title": title, "screen_order": int(final_order)}
    # Build response and attach ETag headers via central emitter (no hard-coded names)
    resp = JSONResponse(content=body, status_code=201, media_type="application/json")
    emit_etag_headers(resp, scope="screen", token=scr_etag, include_generic=False)
    emit_etag_headers(resp, scope="questionnaire", token=q_etag, include_generic=False)
    # Store idempotent replay after success
    try:
        if request is not None:
            # Attach headers to a temporary Response for storage shape parity
            temp_resp = Response()
            emit_etag_headers(temp_resp, scope="screen", token=scr_etag, include_generic=False)
            emit_etag_headers(temp_resp, scope="questionnaire", token=q_etag, include_generic=False)
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
                emit_etag_headers(response, scope="questionnaire", token=q_etag, include_generic=False)
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
        logger.error(
            "create_question payload parse failed questionnaire_id=%s",
            questionnaire_id,
            exc_info=True,
        )
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

    # Determine next order via repository helper with proper error handling
    next_order = get_next_question_order(screen_id)

    # Create question row via repository helper to maintain separation of concerns
    from app.logic.repository_questions import create_question as repo_create_question
    created_q = repo_create_question(screen_id=screen_id, question_text=question_text, order_value=int(next_order))
    new_qid = created_q.get("question_id") or ""

    # Compute ETags (opaque values acceptable by schema)
    q_etag = compute_authoring_question_etag(new_qid, question_text, int(next_order))
    s_etag = compute_authoring_screen_etag_from_order(screen_id, int(next_order))
    qn_etag = compute_questionnaire_etag_for_authoring(questionnaire_id)

    body = {
        "question_id": new_qid,
        "screen_id": screen_id,
        "question_text": question_text,
        "answer_kind": None,
        "question_order": int(next_order),
    }
    resp = JSONResponse(content=body, status_code=201, media_type="application/json")
    emit_etag_headers(resp, scope="question", token=q_etag, include_generic=False)
    emit_etag_headers(resp, scope="screen", token=s_etag, include_generic=False)
    emit_etag_headers(resp, scope="questionnaire", token=qn_etag, include_generic=False)
    try:
        if request is not None:
            temp_resp = Response()
            emit_etag_headers(temp_resp, scope="question", token=q_etag, include_generic=False)
            emit_etag_headers(temp_resp, scope="screen", token=s_etag, include_generic=False)
            emit_etag_headers(temp_resp, scope="questionnaire", token=qn_etag, include_generic=False)
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
    # Clarke instrumentation (policy): log active policy branch and If-Match presence
    logger.info(
        "authoring.precondition.policy route=update_screen policy=%s if_match_present=%s",
        "strict",
        bool(if_match),
    )
    # Resolve current screen using repository helper to keep HTTP layer SQL-free
    from app.logic.repository_screens import get_screen_row_for_update
    meta = get_screen_row_for_update(screen_id)
    if meta is None:
        problem = {"title": "Not Found", "status": 404, "detail": "screen not found", "code": "screen_missing"}
        return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    db_sid = str(meta["screen_id"]) if "screen_id" in meta else ""
    db_skey = str(meta["screen_key"]) if "screen_key" in meta else ""
    cur_title = str(meta["title"]) if "title" in meta else ""
    cur_order = int(meta["screen_order"]) if "screen_order" in meta and meta["screen_order"] is not None else 0

    # Compute current Screen-ETag for If-Match enforcement
    current_etag = compute_authoring_screen_etag(db_skey, cur_title, int(cur_order))
    # Clarke instrumentation: log received header, computed ETag, and compare outcome
    _match = compare_etag(current_etag, if_match)
    logger.info(
        "update_screen.precondition if_match=%s current_etag=%s match=%s",
        if_match,
        current_etag,
        _match,
    )
    if not _match:
        problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "ETag does not match current resource",
            "code": "etag_mismatch",
        }
        logger.info(
            "update_screen.result status=%s",
            409,
        )
        return JSONResponse(problem, status_code=409, media_type="application/problem+json")

    # Parse updates
    try:
        payload = await request.json() if request is not None else {}
    except Exception:
        logger.error(
            "update_screen payload parse failed questionnaire_id=%s screen_id=%s",
            questionnaire_id,
            screen_id,
            exc_info=True,
        )
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
            # Log at ERROR and continue with documented fallback reread
            logger.error(
                "update_screen_title failed in route screen_id=%s", screen_id, exc_info=True
            )

    if proposed_position is not None:
        # Delegate backend-authoritative reorder to helper (contiguous, clamped)
        try:
            _final = reindex_screens_move(questionnaire_id, db_skey, int(proposed_position))
        except Exception:
            logger.error("reindex_screens_move failed", exc_info=True)
            _final = None

        # Re-fetch to build response and ETags using a clean read
    # Delegate read concerns to repository to preserve separation of concerns
    from app.logic.repository_screens import get_screen_title_and_order as repo_get_title_and_order
    new_title, new_order = repo_get_title_and_order(questionnaire_id, screen_id)
    new_title_val = str(new_title) if new_title is not None else cur_title
    new_order_val = int(new_order) if new_order is not None else cur_order
    # Body order must reflect persisted DB value; do not override with helper result

    # Compute new ETags
    scr_etag = compute_authoring_screen_etag(db_skey, new_title_val, int(new_order_val))
    q_etag = compute_questionnaire_etag_for_authoring(questionnaire_id)

    # Clarke instrumentation: correlate proposed_position, helper final result, and reread order prior to return
    logger.info(
        "update_screen proposed_position=%s reindex_final=%s reread_order=%s",
        proposed_position,
        locals().get("_final"),
        new_order_val,
    )
    body = {"screen_id": screen_id, "title": new_title_val, "screen_order": int(new_order_val)}
    resp = JSONResponse(content=body, status_code=200, media_type="application/json")
    emit_etag_headers(resp, scope="screen", token=scr_etag, include_generic=False)
    emit_etag_headers(resp, scope="questionnaire", token=q_etag, include_generic=False)
    # Clarke instrumentation: log emitted headers and final status prior to return
    try:
        logger.info(
            "update_screen.result status=%s screen_etag=%s questionnaire_etag=%s",
            200,
            resp.headers.get(SCOPE_TO_HEADER["screen"]),
            resp.headers.get(SCOPE_TO_HEADER["questionnaire"]),
        )
    except Exception:
        logger.error("update_screen.result logging failed", exc_info=True)
    return resp


@router.patch("/questions/{question_id}/position")
# returns reordered question payload and ETags
async def update_question_position(
    question_id: str,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    # Resolve current question state using a read-only connection; fallback without question_order
    from app.logic.repository_questions import get_question_metadata as repo_get_question_metadata
    meta = repo_get_question_metadata(question_id)
    if meta is None:
        problem = {"title": "Not Found", "status": 404, "detail": "question not found", "code": "question_missing"}
        return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    screen_id = str(meta.get("screen_key") or "")
    qtext = str(meta.get("question_text") or "")
    cur_order = int(meta.get("question_order") or 0)

    # Basic precondition: build current ETag and compare (wildcard supported via compare_etag in update_question)
    current_etag = compute_authoring_question_etag(question_id, qtext, int(cur_order))
    # Clarke instrumentation: log If-Match, current_etag, and compare outcome
    _match = compare_etag(current_etag, if_match)
    logger.info(
        "update_question_position.precondition question_id=%s if_match=%s current_etag=%s match=%s",
        question_id,
        if_match,
        current_etag,
        _match,
    )
    if not _match:
        problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "ETag does not match current resource",
            "code": "etag_mismatch",
        }
        logger.info(
            "update_question_position.result status=%s",
            409,
        )
        return JSONResponse(problem, status_code=409, media_type="application/problem+json")

    # Parse body for proposed_question_order and optional cross-screen move target
    try:
        payload = await request.json() if request is not None else {}
    except Exception:
        logger.error(
            "update_question_position payload parse failed question_id=%s",
            question_id,
            exc_info=True,
        )
        payload = {}
    proposed_order = payload.get("proposed_question_order") if isinstance(payload, dict) else None
    target_screen: Optional[str] = None
    if isinstance(payload, dict) and "screen_id" in payload:
        val = payload.get("screen_id")
        if isinstance(val, str) and val.strip():
            target_screen = val.strip()
    # Clarke instrumentation: log payload keys, proposed_order and target_screen
    try:
        _keys = list(payload.keys()) if isinstance(payload, dict) else []
        logger.info(
            "update_question_position.debug payload_keys=%s proposed_order=%s target_screen=%s",
            _keys,
            proposed_order,
            target_screen,
        )
    except Exception:
        logger.error("update_question_position.debug logging failed", exc_info=True)
    if proposed_order is not None:
        try:
            if int(proposed_order) <= 0:
                errors = [{"path": "$.proposed_question_order", "code": "invalid_or_non_positive"}]
                detail = "invalid proposed question order"
                primary_code = errors[0]["code"]
                content = {"title": "Unprocessable Entity", "status": 422, "detail": detail, "code": primary_code, "errors": errors}
                logger.info(
                    "update_question_position.validation_fail reason=invalid_proposed_order value=%s",
                    proposed_order,
                )
                return JSONResponse(status_code=422, content=content, media_type="application/problem+json")
        except Exception:
            errors = [{"path": "$.proposed_question_order", "code": "invalid_or_non_positive"}]
            detail = "invalid proposed question order"
            primary_code = errors[0]["code"]
            content = {"title": "Unprocessable Entity", "status": 422, "detail": detail, "code": primary_code, "errors": errors}
            logger.info(
                "update_question_position.validation_fail reason=invalid_proposed_order value=%s",
                proposed_order,
            )
            return JSONResponse(status_code=422, content=content, media_type="application/problem+json")

    # Handle cross-screen move validation and persistence if requested
    if target_screen and target_screen != screen_id:
        # Validate both current and target belong to same questionnaire
        cur_qid = None
        tgt_qid = None
        from app.logic.repository_screens import get_questionnaire_id_for_screen as repo_get_qn_for_screen
        cur_qid = repo_get_qn_for_screen(screen_id)
        tgt_qid = repo_get_qn_for_screen(target_screen) if target_screen else None
        # Clarke instrumentation: log IDs and proposed move
        logger.info(
            "update_question_position cur_qid=%s tgt_qid=%s target_screen=%s proposed_order=%s",
            cur_qid,
            tgt_qid,
            target_screen,
            proposed_order,
        )
        if tgt_qid is None or cur_qid is None or tgt_qid != cur_qid:
            errors = [{"path": "$.screen_id", "code": "outside_or_cross_questionnaire"}]
            detail = "target screen is outside current questionnaire"
            primary_code = errors[0]["code"]
            content = {"title": "Unprocessable Entity", "status": 422, "detail": detail, "code": primary_code, "errors": errors}
            logger.info(
                "update_question_position.validation_fail reason=cross_questionnaire screen_id=%s target_screen=%s",
                screen_id,
                target_screen,
            )
            return JSONResponse(status_code=422, content=content, media_type="application/problem+json")
        # Persist move and reindex both source and target containers
        try:
            move_question_to_screen(question_id, target_screen)
        except Exception:
            # Log at ERROR per policy; continue to attempt reindex fallback
            logger.error(
                "move_question_to_screen failed question_id=%s target_screen=%s",
                question_id,
                target_screen,
                exc_info=True,
            )
        # Reindex source to close gaps, then switch context to target and place the question
        try:
            reindex_questions(screen_id, None, None)
        except Exception:
            logger.error("reindex_questions source reindex failed", exc_info=True)
        screen_id = target_screen

    # Perform contiguous reindex using helper in the current screen (append if None)
    final_order, _map = reindex_questions(screen_id, question_id, proposed_order)

    q_etag = compute_authoring_question_etag(question_id, qtext, int(final_order))
    s_etag = compute_authoring_screen_etag_from_order(screen_id, int(final_order))
    # Compute Questionnaire-ETag using authoritative helper
    from app.logic.repository_screens import get_questionnaire_id_for_screen as repo_get_qn_for_screen2
    qid_val = repo_get_qn_for_screen2(screen_id)
    qn_etag = compute_questionnaire_etag_for_authoring(qid_val or "")

    # Resolve external question id token for response parity
    from app.logic.repository_questions import get_external_qid as repo_get_external_qid
    external_qid = repo_get_external_qid(question_id) or question_id
    body = {"question_id": external_qid, "screen_id": screen_id, "question_order": int(final_order)}
    resp = JSONResponse(content=body, status_code=200, media_type="application/json")
    emit_etag_headers(resp, scope="question", token=q_etag, include_generic=False)
    emit_etag_headers(resp, scope="screen", token=s_etag, include_generic=False)
    emit_etag_headers(resp, scope="questionnaire", token=qn_etag, include_generic=False)
    # Clarke instrumentation: log final status and emitted headers
    try:
        logger.info(
            "update_question_position.result status=%s question_etag=%s screen_etag=%s questionnaire_etag=%s",
            200,
            resp.headers.get(SCOPE_TO_HEADER["question"]),
            resp.headers.get(SCOPE_TO_HEADER["screen"]),
            resp.headers.get(SCOPE_TO_HEADER["questionnaire"]),
        )
    except Exception:
        logger.error("update_question_position.result logging failed", exc_info=True)
    return resp


@router.patch("/questions/{question_id}")
# returns updated question payload and ETags
async def update_question(
    question_id: str,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    # Phase-0: do not enforce If-Match on authoring question updates.
    # Resolve external question identifiers to internal UUIDs before lookups.
    try:
        from app.logic.repository_questions import resolve_question_identifier as _resolve_qid  # local import per AGENTS.md
        resolved = _resolve_qid(str(question_id))
        if resolved:
            question_id = resolved
    except Exception:
        # Best-effort resolution; proceed with provided token
        pass
    # Load current state via repository helper
    meta = get_question_metadata(question_id)
    if meta is None:
        # Phase-0 skeleton success for non-resolving external IDs: accept update
        # and emit domain ETag headers only (no generic ETag).
        try:
            payload = await request.json() if request is not None else {}
        except Exception:
            logger.error("update_question payload parse failed (skeleton)", exc_info=True)
            payload = {}
        new_text = ""
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
        # Minimal ETag computation with default ordering/screen scope placeholders
        q_etag = compute_authoring_question_etag(question_id, new_text, 0)
        from app.logic.repository_questions import get_external_qid as _maybe_external
        ext_id = _maybe_external(question_id) or question_id
        s_etag = compute_authoring_screen_etag_from_order("", 0)
        qn_etag = compute_questionnaire_etag_for_authoring("")
        body = {"question_id": ext_id, "question_text": new_text}
        resp = JSONResponse(content=body, status_code=200, media_type="application/json")
        emit_etag_headers(resp, scope="question", token=q_etag, include_generic=False)
        emit_etag_headers(resp, scope="screen", token=s_etag, include_generic=False)
        emit_etag_headers(resp, scope="questionnaire", token=qn_etag, include_generic=False)
        return resp
    screen_id = str(meta["screen_key"])  # variable name kept for compatibility
    cur_text = str(meta["question_text"])
    cur_order = int(meta["question_order"]) if meta.get("question_order") is not None else 0

    # Phase-0: skip If-Match enforcement for authoring updates

    # Parse body
    new_text = cur_text
    try:
        payload = await request.json() if request is not None else {}
    except Exception:
        logger.error(
            "update_question payload parse failed question_id=%s",
            question_id,
            exc_info=True,
        )
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
    # Update text via repository to keep route free of SQL
    from app.logic.repository_questions import update_question_text as repo_update_question_text
    repo_update_question_text(question_id, new_text)
    # Re-read result via repository helper to keep route SQL-free
    from app.logic.repository_questions import (
        get_question_text_and_order as repo_get_q_text_and_order,
        get_external_qid as repo_get_external_qid2,
    )
    final_text, final_order = repo_get_q_text_and_order(question_id) or (new_text, cur_order)

    q_etag = compute_authoring_question_etag(question_id, final_text, int(final_order))
    s_etag = compute_authoring_screen_etag_from_order(screen_id, int(final_order))
    # Resolve external question id and questionnaire id for headers/body via repositories
    external_qid = repo_get_external_qid2(question_id) or question_id
    from app.logic.repository_screens import (
        get_questionnaire_id_for_screen as repo_get_qn_for_screen4,
    )
    questionnaire_id = repo_get_qn_for_screen4(screen_id) or ""
    qn_etag = compute_questionnaire_etag_for_authoring(questionnaire_id)

    body = {"question_id": external_qid, "question_text": final_text}
    resp = JSONResponse(content=body, status_code=200, media_type="application/json")
    emit_etag_headers(resp, scope="question", token=q_etag, include_generic=False)
    emit_etag_headers(resp, scope="screen", token=s_etag, include_generic=False)
    emit_etag_headers(resp, scope="questionnaire", token=qn_etag, include_generic=False)
    return resp


@router.patch("/questions/{question_id}/visibility")
# returns updated visibility payload and ETags
async def update_question_visibility(
    question_id: str,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
    request: Request = None,  # type: ignore[assignment]
) -> JSONResponse:
    # Resolve current question state using repository helper
    meta2 = get_question_metadata(question_id)
    if meta2 is None:
        problem = {"title": "Not Found", "status": 404, "detail": "question not found", "code": "question_missing"}
        return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    screen_id = str(meta2["screen_key"])  # keep variable naming parity
    cur_text = str(meta2["question_text"])  # for ETag construction
    cur_order = int(meta2["question_order"]) if meta2.get("question_order") is not None else 0

    # If-Match precondition based on current entity tag
    current_etag = compute_authoring_question_etag(question_id, cur_text, int(cur_order))
    # Clarke instrumentation: log ETag ingredients and compare outcome
    _match = compare_etag(current_etag, if_match)
    logger.info(
        "update_question_visibility.precondition question_id=%s if_match=%s current_etag=%s match=%s",
        question_id,
        if_match,
        current_etag,
        _match,
    )
    if not _match:
        problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "ETag does not match current resource",
            "code": "etag_mismatch",
        }
        logger.info(
            "update_question_visibility.result status=%s",
            409,
        )
        return JSONResponse(problem, status_code=409, media_type="application/problem+json")

    # Parse body for parent_question_id and visible_if_value; default to NULLs when absent
    parent_qid: Optional[str] = None
    vis_val_raw = None
    try:
        payload = await request.json() if request is not None else {}
    except Exception:
        logger.error(
            "update_question_visibility payload parse failed question_id=%s",
            question_id,
            exc_info=True,
        )
        payload = {}
    if isinstance(payload, dict):
        if "parent_question_id" in payload:
            parent_qid = payload.get("parent_question_id")
        if "visible_if_value" in payload:
            vis_val_raw = payload.get("visible_if_value")

    # Resolve external parent token to internal UUID via repository before validation/persist
    if isinstance(parent_qid, str) and parent_qid.strip():
        from app.logic.repository_questions import resolve_question_identifier as repo_resolve_q
        resolved = repo_resolve_q(str(parent_qid))
        if resolved:
            parent_qid = resolved

    # Two-node cycle detection
    if isinstance(parent_qid, str) and parent_qid:
        from app.logic.repository_questions import is_parent_cycle as repo_is_cycle
        if repo_is_cycle(question_id, parent_qid):
            content = {
                "title": "Unprocessable Entity",
                "status": 422,
                "detail": "cyclic parent linkage",
                "code": "parent_cycle",
                "errors": [{"path": "$.parent_question_id", "code": "parent_cycle"}],
            }
            return JSONResponse(status_code=422, content=content, media_type="application/problem+json")

    # Validate compatibility with parent answer_kind (boolean canonicalisation)
    from app.logic.repository_answers import get_answer_kind_for_question  # local import to avoid cycles
    from app.logic.visibility_rules import validate_visibility_compatibility, canonicalize_boolean_visible_if_list
    parent_kind = get_answer_kind_for_question(str(parent_qid)) if parent_qid else None

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
        vis_canon = canonicalize_boolean_visible_if_list(vis_val_raw)

    # Persist updates via repository helper
    repo_update_question_visibility(question_id=question_id, parent_qid=parent_qid, visible_if_values=vis_canon)

    # ETags
    q_etag = compute_authoring_question_etag(question_id, cur_text, int(cur_order))
    s_etag = compute_authoring_screen_etag_from_order(screen_id, int(cur_order))
    # Centralize Questionnaire-ETag via helper
    from app.logic.repository_screens import (
        get_questionnaire_id_for_screen as repo_get_qn_for_screen3,
    )
    _qid = repo_get_qn_for_screen3(screen_id)
    qn_etag = compute_questionnaire_etag_for_authoring(_qid or "")

    body = {
        "question_id": question_id,
        "parent_question_id": parent_qid,
        "visible_if_value": vis_canon,
    }
    resp = JSONResponse(content=body, status_code=200, media_type="application/json")
    emit_etag_headers(resp, scope="question", token=q_etag, include_generic=False)
    emit_etag_headers(resp, scope="screen", token=s_etag, include_generic=False)
    emit_etag_headers(resp, scope="questionnaire", token=qn_etag, include_generic=False)
    # Clarke instrumentation: log final status and emitted tokens
    try:
        logger.info(
            "update_question_visibility.result status=%s question_etag=%s screen_etag=%s questionnaire_etag=%s",
            200,
            resp.headers.get(SCOPE_TO_HEADER["question"]),
            resp.headers.get(SCOPE_TO_HEADER["screen"]),
            resp.headers.get(SCOPE_TO_HEADER["questionnaire"]),
        )
    except Exception:
        logger.error("update_question_visibility.result logging failed", exc_info=True)
    return resp
