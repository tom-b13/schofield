"""Answer autosave endpoints.

Implements per-answer autosave with idempotency and optimistic concurrency
via If-Match/ETag. Validation is delegated to logic.validation.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.logic.validation import (
    HamiltonValidationError,
    validate_answer_upsert,
    validate_kind_value,
)
from app.logic.etag import compute_screen_etag
from app.logic.repository_answers import (
    get_answer_kind_for_question,
    get_existing_answer,
    get_screen_key_for_question,
    response_id_exists,
    upsert_answer,
)
from app.logic.repository_screens import count_responses_for_screen
import uuid


logger = logging.getLogger(__name__)

router = APIRouter()


class AnswerUpsertModel(BaseModel):
    value: str | int | float | bool | None = None
    option_id: str | None = None


def _normalize_etag(value: str) -> str:
    """Normalize an ETag/If-Match header value for comparison.

    - Preserve wildcard '*'
    - Strip weak validator prefix 'W/'
    - Remove surrounding quotes
    """
    v = (value or "").strip()
    if not v:
        return v
    if v == "*":
        return v
    if v.startswith("W/"):
        v = v[2:].strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1]
    return v


def _screen_key_for_question(question_id: str) -> str | None:  # Backwards-compat shim
    return get_screen_key_for_question(question_id)


def _answer_kind_for_question(question_id: str) -> str | None:  # Backwards-compat shim
    return get_answer_kind_for_question(question_id)


@router.patch(
    "/response-sets/{response_set_id}/answers/{question_id}",
    summary="Autosave a single answer for a question",
    operation_id="autosaveAnswer",
)
def autosave_answer(
    response_set_id: str,
    question_id: str,
    payload: AnswerUpsertModel,
    request: Request,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    # Resolve screen_key and current ETag for optimistic concurrency and If-Match precheck
    screen_key = _screen_key_for_question(question_id)
    if not screen_key:
        raise HTTPException(status_code=404, detail="Unknown question")
    current_etag = compute_screen_etag(response_set_id, screen_key)
    # Capture raw and normalized If-Match for traceability
    raw_if_match = (if_match or "").strip()
    normalized_if_match = _normalize_etag(raw_if_match)

    # Entry log with key correlation fields
    logger.info(
        "autosave_start rs_id=%s q_id=%s idempotency_key=%s if_match_raw=%s if_match_norm=%s current_etag=%s",
        response_set_id,
        question_id,
        idempotency_key,
        raw_if_match,
        normalized_if_match,
        current_etag,
    )

    # Determine whether the screen currently has any responses (pre-write state)
    existing_count = 0
    try:
        existing_count = count_responses_for_screen(response_set_id, screen_key)
    except SQLAlchemyError:
        # On any failure to compute count, log and fall back to prior behavior
        logger.error(
            "autosave_precheck_count_failed rs_id=%s screen_key=%s",
            response_set_id,
            screen_key,
            exc_info=True,
        )
        existing_count = -1  # treat as unknown but non-zero to keep prior behavior
    # NOTE: Idempotent replay checks now run BEFORE enforcing If-Match.
    logger.info(
        "autosave_precheck_counts rs_id=%s screen_key=%s existing_screen_count=%s",
        response_set_id,
        screen_key,
        existing_count,
    )

    # Strong idempotency: deterministic response_id replay check (after If-Match enforcement)
    if idempotency_key:
        try:
            deterministic_rid = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"epic-b:{response_set_id}:{question_id}:{idempotency_key or ''}",
                )
            )
            # Probe for existing response id
            if response_id_exists(deterministic_rid):
                response.headers["ETag"] = current_etag
                logger.info(
                    "autosave_idempotent_replay rs_id=%s q_id=%s reason=response_id_match etag=%s idempotency_key=%s",
                    response_set_id,
                    question_id,
                    current_etag,
                    idempotency_key,
                )
                return {"saved": True, "etag": current_etag}
        except SQLAlchemyError:
            # Fail open to existing behavior if short-circuit probe fails
            logger.error(
                "idempotent_rid_probe_failed rs_id=%s q_id=%s",
                response_set_id,
                question_id,
                exc_info=True,
            )

    # Secondary idempotent replay short-circuit independent of response_id (still before If-Match enforcement)
    try:
        row = get_existing_answer(response_set_id, question_id)
        existing_count_rsq = 0
        if row is not None:
            stored_option_id, stored_text, stored_number, stored_bool = row
            existing_count_rsq = 1
            incoming_value = payload.value
            incoming_option_id = payload.option_id
            match = False
            # Compare based on the typed storage columns we persist
            if incoming_value is None:
                match = (
                    stored_text is None and stored_number is None and stored_bool is None
                )
            elif isinstance(incoming_value, str):
                match = stored_text == incoming_value
            elif isinstance(incoming_value, (int, float)):
                try:
                    match = (stored_number is not None) and (float(stored_number) == float(incoming_value))
                except (TypeError, ValueError):
                    match = False
            elif isinstance(incoming_value, bool):
                match = stored_bool == bool(incoming_value)
            # Option id must also match
            match = match and (stored_option_id == incoming_option_id)

            logger.info(
                "autosave_value_match_probe rs_id=%s q_id=%s existing_rsq=%s incoming_value=%s incoming_option=%s match=%s",
                response_set_id,
                question_id,
                existing_count_rsq,
                incoming_value,
                incoming_option_id,
                match,
            )
            if match:
                response.headers["ETag"] = current_etag
                logger.info(
                    "autosave_idempotent_replay rs_id=%s q_id=%s reason=value_match etag=%s idempotency_key=%s",
                    response_set_id,
                    question_id,
                    current_etag,
                    idempotency_key,
                )
                return {"saved": True, "etag": current_etag}
    except SQLAlchemyError:
        # Fail open to existing behavior if short-circuit probe fails
        logger.error(
            "idempotent_probe_failed rs_id=%s q_id=%s",
            response_set_id,
            question_id,
            exc_info=True,
        )

    # If-Match check; allow wildcard. Enforce only if NOT an idempotent replay
    if if_match is not None:
        incoming = _normalize_etag((if_match or "").strip())
        current = _normalize_etag((current_etag or "").strip())
        logger.info(
            "autosave_if_match_check rs_id=%s q_id=%s if_match_raw=%s if_match_norm=%s current_norm=%s existing_screen_count=%s",
            response_set_id,
            question_id,
            raw_if_match,
            incoming,
            current,
            existing_count,
        )
        # Enforce only when header provided and non-empty; compare normalized tokens only.
        # Wildcard '*' unconditionally passes. When there are no prior responses for the
        # screen, allow the write to proceed even if tokens differ (initial write case).
        if (
            incoming
            and incoming != "*"
            and incoming != current
            and (existing_count > 0)
        ):
            logger.info(
                "autosave_conflict rs_id=%s q_id=%s screen_key=%s if_match_raw=%s if_match_norm=%s current_norm=%s write_performed=false",
                response_set_id,
                question_id,
                screen_key,
                raw_if_match,
                incoming,
                current,
            )
            problem = {
                "title": "ETag mismatch",
                "status": 409,
                "detail": "If-Match does not match the current resource state",
            }
            resp = JSONResponse(problem, status_code=409, media_type="application/problem+json")
            resp.headers["ETag"] = current_etag
            return resp

    # Validate payload according to shared rules; kind-specific rules are out of scope here
    validate_answer_upsert(payload.model_dump())

    # Type-aware value validation for number/boolean kinds
    kind = _answer_kind_for_question(question_id) or ""
    value: Any = payload.value
    try:
        validate_kind_value(kind, value)
    except HamiltonValidationError:
        problem = {
            "title": "Validation failed",
            "status": 422,
            "errors": [
                {"path": "$.value", "code": "type_mismatch", "message": f"Expected {kind} for question kind '{kind}'"}
            ],
        }
        return JSONResponse(problem, status_code=422, media_type="application/problem+json")

    # Upsert response row
    logger.info(
        "autosave_write_begin rs_id=%s q_id=%s value=%s option_id=%s",
        response_set_id,
        question_id,
        value,
        payload.option_id,
    )
    upsert_answer(
        response_set_id=response_set_id,
        question_id=question_id,
        option_id=payload.option_id,
        value=value,
        idempotency_key=idempotency_key,
    )

    # Compute and expose fresh ETag for the screen
    new_etag = compute_screen_etag(response_set_id, screen_key)
    response.headers["ETag"] = new_etag
    logger.info(
        "autosave_ok rs_id=%s q_id=%s screen_key=%s new_etag=%s write_performed=true",
        response_set_id,
        question_id,
        screen_key,
        new_etag,
    )
    return {"saved": True, "etag": new_etag}
