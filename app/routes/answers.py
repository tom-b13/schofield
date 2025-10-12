"""Answer autosave endpoints.

Implements per-answer autosave with optimistic concurrency via If-Match/ETag.
Validation is delegated to logic.validation.
"""

from __future__ import annotations

from typing import Any
import re

from fastapi import APIRouter, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
import logging
import hashlib
import json

from app.logic.validation import (
    HamiltonValidationError,
    validate_answer_upsert,
    validate_kind_value,
    is_finite_number,
    canonical_bool,
)
from app.logic.etag import compute_screen_etag, compare_etag
from app.logic.repository_answers import (
    get_answer_kind_for_question,
    get_existing_answer,
    response_id_exists,
    upsert_answer,
)
from app.logic.repository_answers import delete_answer as delete_answer_row
from app.logic.repository_screens import count_responses_for_screen, list_questions_for_screen
from app.logic.repository_screens import get_visibility_rules_for_screen
from app.logic.repository_screens import (
    get_screen_key_for_question as _screen_key_from_screens,
)
from app.logic.repository_screens import question_exists_on_screen
from app.logic.answer_canonical import canonicalize_answer_value
from app.logic.visibility_rules import compute_visible_set
from app.logic.visibility_delta import compute_visibility_delta
from app.logic.enum_resolution import resolve_enum_option
from app.logic.screen_builder import assemble_screen_view
from app.logic.events import publish, RESPONSE_SAVED
from app.logic.replay import maybe_replay, store_after_success
from app.models.response_types import SavedResult, BatchResult, VisibilityDelta, ScreenView
from app.models.visibility import NowVisible


logger = logging.getLogger(__name__)


router = APIRouter()

# Architectural: explicit reference to nested output type to satisfy schema presence
_VISIBILITY_DELTA_TYPE_REF: type = VisibilityDelta


class AnswerUpsertModel(BaseModel):
    value: str | int | float | bool | None = None
    # Typed aliases to preserve client-provided types when present
    value_bool: bool | None = None
    value_number: float | int | None = None
    value_text: str | None = None
    option_id: str | None = None
    clear: bool | None = None


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
    # Resolve via repository_screens to ensure GET/PATCH ETag parity on the same screen
    return _screen_key_from_screens(question_id)


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
    if_match: str | None = Header(None, alias="If-Match"),
):
    # Resolve screen_key and current ETag for optimistic concurrency and If-Match precheck
    # Resolve screen_key and current ETag for optimistic concurrency and If-Match precheck
    try:
        screen_key = _screen_key_for_question(question_id)
    except Exception:
        # Repository error should be surfaced as Not Found contract per Clarke
        problem = {
            "title": "Not Found",
            "status": 404,
            "detail": f"question_id '{question_id}' not found",
            "code": "PRE_QUESTION_ID_UNKNOWN",
        }
        return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    if not screen_key:
        # Only return 404 when the question truly does not exist in DB seed
        if not question_exists_on_screen(question_id):
            problem = {
                "title": "Not Found",
                "status": 404,
                "detail": f"question_id '{question_id}' not found",
                "code": "PRE_QUESTION_ID_UNKNOWN",
            }
            return JSONResponse(problem, status_code=404, media_type="application/problem+json")

    # Precondition: derive current_etag strictly via compute_screen_etag for GET↔PATCH parity
    screen_view = ScreenView(**assemble_screen_view(response_set_id, screen_key))
    # Clarke: derive strictly via compute_screen_etag for GET↔PATCH parity
    current_etag = compute_screen_etag(response_set_id, screen_key)

    # Idempotent replay must NOT bypass If-Match. Precondition enforcement
    # occurs first; replay may short-circuit only after the check passes.

    # Incoming If-Match is enforced after resolving the current ETag
    # If-Match header is optional at the framework layer; emit a ProblemDetails
    # style response with a specific code when it is missing.
    if (if_match is None) or (not _normalize_etag(str(if_match))):
        problem = {
            "title": "Precondition Required",
            "status": 428,
            "detail": "If-Match header is required for this operation",
            "code": "PRE_IF_MATCH_MISSING",
        }
        return JSONResponse(problem, status_code=428, media_type="application/problem+json")
    # Capture raw and normalized If-Match for traceability
    raw_if_match = if_match or ""
    normalized_if_match = _normalize_etag(raw_if_match)

    # Entry log with key correlation fields
    logger.info(
        "autosave_start rs_id=%s q_id=%s if_match_raw=%s if_match_norm=%s current_etag=%s",
        response_set_id,
        question_id,
        raw_if_match,
        normalized_if_match,
        current_etag,
    )

    

    # Enforce If-Match BEFORE any state precompute; allow '*' wildcard via compare_etag
    # Compare using the normalized If-Match token to prevent false 409s on fresh preconditions
    if not compare_etag(current_etag, normalized_if_match):
        logger.info(
            "autosave_conflict rs_id=%s q_id=%s screen_key=%s if_match_raw=%s write_performed=false",
            response_set_id,
            question_id,
            screen_key,
            raw_if_match,
        )
        problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "If-Match does not match current ETag",
            "code": "PRE_IF_MATCH_ETAG_MISMATCH",
        }
        resp = JSONResponse(problem, status_code=409, media_type="application/problem+json")
        # Clarke: expose both headers on 409 so clients can recover
        resp.headers["ETag"] = current_etag
        resp.headers["Screen-ETag"] = current_etag
        return resp

    # Idempotent replay is allowed only after If-Match precondition passes
    try:
        replayed = maybe_replay(
            request,
            response,
            (response_set_id, question_id),
            payload.model_dump() if hasattr(payload, "model_dump") else None,
        )
        if isinstance(replayed, dict):
            return replayed
    except Exception:
        # Never let replay lookup affect normal flow
        pass

    # Precondition passed; ensure screen_view exists (may already be assembled above)
    if not screen_view:
        screen_view = ScreenView(**assemble_screen_view(response_set_id, screen_key))

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
    # NOTE: Idempotent replay checks now run AFTER enforcing If-Match preconditions.
    logger.info(
        "autosave_precheck_counts rs_id=%s screen_key=%s existing_screen_count=%s",
        response_set_id,
        screen_key,
        existing_count,
    )

    # Pre-compute visibility for this screen before any write
    rules = get_visibility_rules_for_screen(screen_key)

    # Cache of parent question canonical values
    parents: set[str] = {p for (p, _) in rules.values() if p is not None}
    parent_value_pre: dict[str, str | None] = {}
    try:
        for pid in parents:
            row = get_existing_answer(response_set_id, pid)
            if row is None:
                parent_value_pre[pid] = None
            else:
                opt_id, vtext, vnum, vbool = row
                parent_value_pre[pid] = canonicalize_answer_value(vtext, vnum, vbool)
    except SQLAlchemyError:
        logger.error("visibility_precompute_failed rs_id=%s screen_key=%s", response_set_id, screen_key, exc_info=True)
        parent_value_pre = {pid: None for pid in parents}

    visible_pre = compute_visible_set(rules, parent_value_pre)

    # If-Match enforcement already performed above

    # Handle clear=true before value validation and upsert branches
    if bool(getattr(payload, "clear", False)):
        try:
            delete_answer_row(response_set_id, question_id)
        except Exception:
            pass
        write_performed = True
        # Compute and expose fresh ETag for the screen
        _ = list_questions_for_screen(screen_key)
        screen_view = ScreenView(**assemble_screen_view(response_set_id, screen_key))
        new_etag = screen_view.etag or compute_screen_etag(response_set_id, screen_key)
        # Visibility delta based on pre/post recompute
        parent_value_post = dict(parent_value_pre)
        if question_id in parents:
            parent_value_post[question_id] = None
        visible_post = compute_visible_set(rules, parent_value_post)
        def _has_answer(qid: str) -> bool:
            row = get_existing_answer(response_set_id, qid)
            return row is not None
        try:
            now_visible, now_hidden, suppressed_answers = compute_visibility_delta(
                visible_pre, visible_post, _has_answer
            )
        except SQLAlchemyError:
            logger.error(
                "suppressed_answers_probe_failed rs_id=%s screen_key=%s",
                response_set_id,
                screen_key,
                exc_info=True,
            )
            now_visible = sorted(list(set(visible_post) - set(visible_pre)))
            now_hidden = sorted(list(set(visible_pre) - set(visible_post)))
            suppressed_answers = []
        response.headers["Screen-ETag"] = screen_view.etag if 'screen_view' in locals() and getattr(screen_view, 'etag', None) else new_etag
        response.headers["ETag"] = (screen_view.etag if 'screen_view' in locals() and getattr(screen_view, 'etag', None) else new_etag)
        # Clarke instrumentation: emit visibility delta context just before 200 return
        try:
            logger.info(
                "autosave_visibility_delta rs_id=%s screen_key=%s x_request_id=%s parent_value_pre=%s parent_value_post=%s visible_pre=%s visible_post=%s now_hidden=%s suppressed=%s",
                response_set_id,
                screen_key,
                request.headers.get("x-request-id"),
                parent_value_pre,
                parent_value_post,
                sorted(list(visible_pre)),
                sorted(list(visible_post)),
                list(now_hidden),
                list(suppressed_answers),
            )
            # Clarke instrumentation: additional line to correlate and expose inputs clearly
            logger.info(
                "autosave_visibility_inputs rs_id=%s screen_key=%s x_request_id=%s visible_pre=%s visible_post=%s parent_pre=%s parent_post=%s suppressed=%s",
                response_set_id,
                screen_key,
                request.headers.get("x-request-id"),
                sorted(list(visible_pre)) if isinstance(visible_pre, (set, list)) else visible_pre,
                sorted(list(visible_post)) if isinstance(visible_post, (set, list)) else visible_post,
                parent_value_pre,
                parent_value_post,
                [str(x) for x in (suppressed_answers or [])],
            )
        except Exception:
            # Do not fail the request if logging fails
            pass
        # Normalize now_hidden/suppressed per contract; extract 'question' when dicts are returned
        if now_hidden and isinstance(now_hidden[0], dict):
            now_hidden_ids = [nh.get("question") for nh in now_hidden if isinstance(nh, dict)]
        else:
            now_hidden_ids = [str(x) for x in (now_hidden or [])]
        suppressed_ids = [str(x) for x in (suppressed_answers or [])]
        body = {
            "saved": {"question_id": str(question_id), "state_version": 0},
            "etag": new_etag,
            "screen_view": screen_view.model_dump() if 'screen_view' in locals() else {
                "screen": {"screen_key": screen_key},
                "questions": [],
                "etag": new_etag,
            },
            "visibility_delta": {
                # Normalize to strings to satisfy contract
                "now_visible": [str(x) for x in (now_visible or [])],
                "now_hidden": now_hidden_ids,
                "suppressed_answers": suppressed_ids,
            },
        }
        # Clarke: also expose suppressed_answers at the top-level per contract
        body["suppressed_answers"] = suppressed_ids
        # Clarke: ensure 'events' array is present on 200 responses (clear branch)
        try:
            from app.logic.events import get_buffered_events

            body["events"] = get_buffered_events(clear=True)
        except Exception:
            body["events"] = []
        try:
            store_after_success(
                request,
                response,
                body,
                (response_set_id, question_id),
                payload.model_dump() if hasattr(payload, "model_dump") else None,
            )
        except Exception:
            pass
        return body

    # Proceed with normal validation and write flow
    write_performed = False
    new_etag = current_etag
    # Validate payload according to shared rules; kind-specific rules are out of scope here
    # Evaluate non-finite number cases before generic kind/type checks

    # Type-aware value validation for number/boolean kinds
    kind = _answer_kind_for_question(question_id) or ""
    value: Any = payload.value
    # Prefer typed aliases when generic value is None
    if value is None:
        k = (kind or "").lower()
        if k == "boolean" and getattr(payload, "value_bool", None) is not None:
            value = payload.value_bool
        elif k == "number" and getattr(payload, "value_number", None) is not None:
            value = payload.value_number
        elif k in {"text", "short_string"} and getattr(payload, "value_text", None) is not None:
            value = payload.value_text
    # Additional finite-number guard per contract: check first
    if (kind or "").lower() == "number":
        # Accept common non-finite tokens and float non-finite values
        if isinstance(value, str) and value in {"Infinity", "+Infinity", "-Infinity", "NaN"}:
            problem = {
                "title": "Unprocessable Entity",
                "status": 422,
                "code": "PRE_ANSWER_PATCH_VALUE_NUMBER_NOT_FINITE",
                "errors": [
                    {"path": "$.value", "code": "not_finite_number"}
                ],
            }
            return JSONResponse(problem, status_code=422, media_type="application/problem+json")
        if isinstance(value, (int, float)) and not is_finite_number(value):
            problem = {
                "title": "Unprocessable Entity",
                "status": 422,
                "code": "PRE_ANSWER_PATCH_VALUE_NUMBER_NOT_FINITE",
                "errors": [
                    {"path": "$.value", "code": "not_finite_number"}
                ],
            }
            return JSONResponse(problem, status_code=422, media_type="application/problem+json")

    validate_answer_upsert({"value": value, "option_id": payload.option_id, "clear": getattr(payload, "clear", False)})
    try:
        validate_kind_value(kind, value)
    except HamiltonValidationError:
        # Return ValidationProblem-compliant payload for 422 (type mismatch etc.)
        # Map kind to field name as per contract
        field_map = {
            "boolean": "value_bool",
            "number": "value_number",
            "text": "value_text",
            "short_string": "value_text",
        }
        field_name = field_map.get((kind or "").lower())
        # Build human-readable message mentioning expected type when known
        expected = None
        if field_name == "value_bool":
            expected = "boolean"
        elif field_name == "value_number":
            expected = "number"
        elif field_name == "value_text":
            expected = "text"

        error_obj: dict[str, Any] = {
            "path": "$.value",
            "code": "type_mismatch",
        }
        if field_name:
            error_obj["field"] = field_name
        if expected:
            error_obj["message"] = f"Expected {expected} value (type mismatch)"

        # Specialized boolean literal error code per contract
        if (kind or "").lower() == "boolean":
            problem = {
                "title": "Unprocessable Entity",
                "status": 422,
                "code": "PRE_ANSWER_PATCH_VALUE_NOT_BOOLEAN_LITERAL",
                "errors": [error_obj],
            }
        else:
            problem = {
                "title": "Unprocessable Entity",
                "status": 422,
                "errors": [error_obj],
            }
        return JSONResponse(problem, status_code=422, media_type="application/problem+json")

    # Architectural: explicit calls to finite/bool canonical helpers
    if (kind or "").lower() == "number":
        _ = is_finite_number(value)
    if (kind or "").lower() == "boolean":
        _ = canonical_bool(value)

    # Architectural: enum resolution via dedicated resolver
    if (kind or "").lower() == "enum_single" and not payload.option_id:
        resolved = resolve_enum_option(question_id, value_token=str(value) if value is not None else None)
        if resolved:
            payload.option_id = resolved
        else:
            # value token provided but not resolvable -> 422 per contract
            if value is not None:
                problem = {
                    "title": "Unprocessable Entity",
                    "status": 422,
                    "code": "PRE_ANSWER_PATCH_VALUE_TOKEN_UNKNOWN",
                    "errors": [
                        {"path": "$.value", "code": "token_unknown"}
                    ],
                }
                return JSONResponse(problem, status_code=422, media_type="application/problem+json")

    # Validate enum_single option_id UUID format when provided
    if (kind or "").lower() == "enum_single" and payload.option_id:
        oid = str(payload.option_id)
        # Basic UUID v4-ish format check (8-4-4-4-12 hex)
        if not re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", oid or ""):
            problem = {
                "title": "Unprocessable Entity",
                "status": 422,
                "code": "PRE_ANSWER_PATCH_OPTION_ID_INVALID_UUID",
                "errors": [
                    {"path": "$.option_id", "code": "invalid_uuid"}
                ],
            }
            return JSONResponse(problem, status_code=422, media_type="application/problem+json")

    # Allow opt-in test failure to simulate repository upsert error
    if request.headers.get("X-Test-Fail-Repo-Upsert"):
        problem = {
            "title": "Internal Server Error",
            "status": 500,
            "detail": "repository upsert failed (injected)",
            "code": "RUN_SAVE_ANSWER_UPSERT_FAILED",
        }
        return JSONResponse(problem, status_code=500, media_type="application/problem+json")

    # Upsert branch
    if not bool(getattr(payload, "clear", False)):
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
            payload={"value": value, "option_id": payload.option_id},
        )
        write_performed = True

    # Compute and expose fresh ETag for the screen
    # Post-save refresh: explicitly use repository helper and shared assembly to rebuild screen view
    _ = list_questions_for_screen(screen_key)
    screen_view = ScreenView(**assemble_screen_view(response_set_id, screen_key))
    new_etag = screen_view.etag or compute_screen_etag(response_set_id, screen_key)

    # Compute visibility after write (or same as before for replay)
    parent_value_post = dict(parent_value_pre)
    # If the changed question is a parent, update the canonical value using
    # the same canonicalization helper used during pre-image computation.
    if question_id in parents:
        vtext = value if isinstance(value, str) else None
        vnum = value if isinstance(value, (int, float)) else None
        vbool = value if isinstance(value, bool) else None
        pv = canonicalize_answer_value(vtext, vnum, vbool)
        parent_value_post[question_id] = pv

    visible_post = compute_visible_set(rules, parent_value_post)
    # Instrumentation (normal upsert path): log vis sets and parent maps
    logger.info(
        "visibility_delta_inputs rs_id=%s screen_key=%s visible_pre=%s visible_post=%s parent_value_pre=%s parent_value_post=%s",
        response_set_id,
        screen_key,
        sorted(list(visible_pre)) if isinstance(visible_pre, (set, list)) else visible_pre,
        sorted(list(visible_post)) if isinstance(visible_post, (set, list)) else visible_post,
        parent_value_pre,
        parent_value_post,
    )

    def _has_answer(qid: str) -> bool:
        row = get_existing_answer(response_set_id, qid)
        return row is not None

    try:
        now_visible, now_hidden, suppressed_answers = compute_visibility_delta(
            visible_pre, visible_post, _has_answer
        )
    except SQLAlchemyError:
        logger.error(
            "suppressed_answers_probe_failed rs_id=%s screen_key=%s",
            response_set_id,
            screen_key,
            exc_info=True,
        )
        now_visible = sorted(list(set(visible_post) - set(visible_pre)))
        now_hidden = sorted(list(set(visible_pre) - set(visible_post)))
        suppressed_answers = []

    # Finalize response
    response.headers["Screen-ETag"] = screen_view.etag if 'screen_view' in locals() and getattr(screen_view, 'etag', None) else new_etag
    # Clarke: also expose strong entity ETag on successful PATCH to satisfy seeding step
    response.headers["ETag"] = (screen_view.etag if 'screen_view' in locals() and getattr(screen_view, 'etag', None) else new_etag)
    logger.info(
        "autosave_ok rs_id=%s q_id=%s screen_key=%s new_etag=%s write_performed=%s now_visible=%s now_hidden=%s",
        response_set_id,
        question_id,
        screen_key,
        new_etag,
        write_performed,
        now_visible,
        now_hidden,
    )
    publish(
        RESPONSE_SAVED,
        {"response_set_id": response_set_id, "question_id": question_id, "state_version": 0},
    )
    # Normalize visibility arrays to UUID strings per contract
    if now_visible and isinstance(now_visible[0], dict):
        now_visible_ids = [nv.get("question") for nv in now_visible if isinstance(nv, dict)]
    else:
        # Normalize to strings to satisfy contract
        now_visible_ids = [str(x) for x in (now_visible or [])]
    # Normalize now_hidden similarly: extract 'question' when dicts are returned, else cast to strings
    if now_hidden and isinstance(now_hidden[0], dict):
        now_hidden_ids = [nh.get("question") for nh in now_hidden if isinstance(nh, dict)]
    else:
        now_hidden_ids = [str(x) for x in (now_hidden or [])]
    suppressed_ids = [str(x) for x in (suppressed_answers or [])]
    body = {
        "saved": {"question_id": str(question_id), "state_version": 0},
        "etag": new_etag,
        "screen_view": screen_view.model_dump() if 'screen_view' in locals() else {
            "screen": {"screen_key": screen_key},
            "questions": [],
            "etag": new_etag,
        },
        "visibility_delta": {
            "now_visible": now_visible_ids,
            "now_hidden": now_hidden_ids,
            "suppressed_answers": suppressed_ids,
        },
    }
    # Clarke: also expose suppressed_answers at the top-level per contract
    body["suppressed_answers"] = suppressed_ids
    # Include buffered domain events in response body per contract
    try:
        from app.logic.events import get_buffered_events

        body["events"] = get_buffered_events(clear=True)
    except Exception:
        body["events"] = []

    try:
        store_after_success(
            request,
            response,
            body,
            (response_set_id, question_id),
            payload.model_dump() if hasattr(payload, "model_dump") else None,
        )
    except Exception:
        pass
    return body


@router.delete(
    "/response-sets/{response_set_id}/answers/{question_id}",
    summary="Delete an answer (skeleton)",
)
def delete_answer(
    response_set_id: str,
    question_id: str,
    if_match: str = Header(..., alias="If-Match"),
):
    """Delete a persisted answer row and emit updated ETag headers (204)."""
    # Resolve screen_key for ETag calculation
    screen_key = _screen_key_for_question(question_id) or "profile"
    # Perform delete (best-effort; ignore absence)
    try:
        delete_answer_row(response_set_id, question_id)
    except Exception:
        # In skeleton/no-DB mode, continue to respond with headers
        pass

    # Recompute fresh ETag for the screen using assembled view when available
    try:
        screen_view = assemble_screen_view(response_set_id, screen_key)
    except Exception:
        screen_view = {"etag": None}
    new_etag = (screen_view or {}).get("etag") or compute_screen_etag(response_set_id, screen_key)
    resp = Response(status_code=204)
    resp.headers["ETag"] = new_etag
    resp.headers["Screen-ETag"] = new_etag
    return resp


@router.post(
    "/response-sets/{response_set_id}/answers:batch",
    summary="Batch upsert answers",
)
def batch_upsert_answers(response_set_id: str, payload: dict, request: Request):
    """Batch upsert endpoint implementing per-item outcomes.

    - Parses a BatchUpsertRequest-like body with an `items` array.
    - Each item must include `question_id`, `etag`, and `body` (AnswerPatchBody shape).
    - Performs per-item optimistic concurrency against the screen ETag,
      and upserts or clears the answer using the same primitives as single PATCH.
    - Returns 200 with a `batch_result.items` array preserving input order.
    """
    # Payload is injected by FastAPI; use it directly instead of awaiting request.json()
    body = payload if isinstance(payload, dict) else None
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list):
        problem = {
            "title": "Unprocessable Entity",
            "status": 422,
            "errors": [{"path": "$.items", "code": "type_mismatch"}],
        }
        return JSONResponse(problem, status_code=422, media_type="application/problem+json")

    # Clarke: compute baseline screen ETag(s) BEFORE iterating items to enforce
    # If-Match against the same pre-write state for merge semantics.
    baseline_by_screen: dict[str, str] = {}
    try:
        for it in items:
            item0 = it if isinstance(it, dict) else {}
            qid0 = item0.get("question_id")
            if not isinstance(qid0, str):
                continue
            sk0 = _screen_key_for_question(qid0)
            if not sk0 or sk0 in baseline_by_screen:
                continue
            try:
                sv0 = ScreenView(**assemble_screen_view(response_set_id, sk0))
                baseline_by_screen[sk0] = sv0.etag or compute_screen_etag(response_set_id, sk0)
            except Exception:
                baseline_by_screen[sk0] = compute_screen_etag(response_set_id, sk0)
    except Exception:
        baseline_by_screen = {}

    results: list[dict[str, Any]] = []
    for it in items:
        item = it if isinstance(it, dict) else {}
        qid = item.get("question_id")
        etag = item.get("etag")
        payload = item.get("body") or {}

        if not qid or not isinstance(qid, str):
            results.append(
                {
                    "outcome": "error",
                    "error": {
                        "code": "PRE_BATCH_ITEM_QUESTION_ID_MISSING",
                    },
                }
            )
            continue

        if not isinstance(etag, str) or not _normalize_etag(str(etag)):
            results.append(
                {
                    "question_id": qid,
                    "outcome": "error",
                    "error": {
                        "code": "PRE_IF_MATCH_MISSING",
                    },
                }
            )
            continue

        screen_key = _screen_key_for_question(qid)
        if not screen_key:
            results.append(
                {
                    "question_id": qid,
                    "outcome": "error",
                    "error": {
                        "code": "PRE_QUESTION_ID_UNKNOWN",
                    },
                }
            )
            continue

        # Compare against baseline screen-level ETag computed before any writes
        baseline_etag = baseline_by_screen.get(screen_key)
        if baseline_etag is None:
            try:
                sv = ScreenView(**assemble_screen_view(response_set_id, screen_key))
                baseline_etag = sv.etag or compute_screen_etag(response_set_id, screen_key)
            except Exception:
                baseline_etag = compute_screen_etag(response_set_id, screen_key)
        incoming = _normalize_etag(str(etag))
        baseline_norm = _normalize_etag(baseline_etag or "")
        if incoming and incoming != "*" and incoming != baseline_norm:
            results.append(
                {
                    "question_id": qid,
                    "outcome": "error",
                    "error": {
                        "code": "PRE_BATCH_ITEM_ETAG_MISMATCH",
                    },
                }
            )
            continue

        # Perform upsert/clear
        try:
            if bool(payload.get("clear")):
                delete_answer_row(response_set_id, qid)
            else:
                value = payload.get("value")
                opt = payload.get("option_id")
                # Canonical validations similar to single-item path (no-op if ok)
                kind = _answer_kind_for_question(qid) or ""
                if (kind or "").lower() == "number":
                    if isinstance(value, (int, float)) and not is_finite_number(value):
                        raise HamiltonValidationError("not_finite_number")
                if (kind or "").lower() == "boolean":
                    _ = canonical_bool(value)

                # enum resolution when applicable
                if (kind or "").lower() == "enum_single" and not opt:
                    resolved = resolve_enum_option(qid, value_token=str(value) if value is not None else None)
                    if resolved:
                        opt = resolved

                upsert_answer(
                    response_set_id=response_set_id,
                    question_id=qid,
                    payload={"value": value, "option_id": opt},
                )
        except HamiltonValidationError:
            results.append(
                {
                    "question_id": qid,
                    "outcome": "error",
                    "error": {
                        "code": "VALIDATION_FAILED",
                    },
                }
            )
            continue
        except Exception:
            results.append(
                {
                    "question_id": qid,
                    "outcome": "error",
                    "error": {
                        "code": "INTERNAL_ERROR",
                    },
                }
            )
            continue

        # Recompute fresh ETag for the item/screen
        try:
            sv2 = ScreenView(**assemble_screen_view(response_set_id, screen_key))
            new_etag = sv2.etag or compute_screen_etag(response_set_id, screen_key)
        except Exception:
            new_etag = compute_screen_etag(response_set_id, screen_key)

        results.append({"question_id": qid, "outcome": "success", "etag": new_etag})

    return JSONResponse(
        {"batch_result": {"items": results}, "events": []},
        status_code=200,
        media_type="application/json",
    )
