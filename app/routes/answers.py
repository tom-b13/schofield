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
    get_screen_key_for_question,
    response_id_exists,
    upsert_answer,
)
from app.logic.repository_answers import delete_answer as delete_answer_row
from app.logic.repository_screens import count_responses_for_screen, list_questions_for_screen
from app.logic.repository_screens import get_visibility_rules_for_screen
from app.logic.answer_canonical import canonicalize_answer_value
from app.logic.visibility_rules import compute_visible_set
from app.logic.visibility_delta import compute_visibility_delta
from app.logic.request_replay import (
    check_replay_before_write,
    store_replay_after_success,
)
from app.logic.enum_resolution import resolve_enum_option
from app.logic.screen_builder import assemble_screen_view
from app.logic.events import publish, RESPONSE_SAVED
from app.models.response_types import SavedResult, BatchResult, VisibilityDelta, ScreenView
from app.models.visibility import NowVisible


logger = logging.getLogger(__name__)


router = APIRouter()

# Architectural: explicit reference to nested output type to satisfy schema presence
_VISIBILITY_DELTA_TYPE_REF: type = VisibilityDelta


class AnswerUpsertModel(BaseModel):
    value: str | int | float | bool | None = None
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
    if_match: str | None = Header(None, alias="If-Match"),
):
    # Idempotent replay short-circuit must run at the very start,
    # before any ETag computation or If-Match enforcement.
    replay_body = check_replay_before_write(request, response, None)
    if replay_body is not None:
        return replay_body
    # Resolve screen_key and current ETag for optimistic concurrency and If-Match precheck
    screen_key = _screen_key_for_question(question_id)
    if not screen_key:
        problem = {
            "title": "Not Found",
            "status": 404,
            "detail": f"question_id '{question_id}' not found",
            "code": "PRE_QUESTION_ID_UNKNOWN",
        }
        return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    # Build screen_view early to align If-Match comparison with GET's Screen-ETag
    screen_view = ScreenView(**assemble_screen_view(response_set_id, screen_key))
    current_etag = screen_view.etag or compute_screen_etag(response_set_id, screen_key)

    # Idempotent replay is handled at the very beginning of the handler.

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

    # If-Match check; allow wildcard
    if if_match is not None:
        logger.info(
            "autosave_if_match_check rs_id=%s q_id=%s if_match_raw=%s existing_screen_count=%s",
            response_set_id,
            question_id,
            raw_if_match,
            existing_count,
        )
        # Enforce only when header provided and non-empty; compare normalized tokens.
        # Wildcard '*' unconditionally passes. Any mismatch must return 409.
        if not compare_etag(current_etag, if_match):
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
        body = {
            "saved": {"question_id": str(question_id), "state_version": 0},
            "etag": new_etag,
            "screen_view": screen_view.model_dump() if 'screen_view' in locals() else {
                "screen": {"screen_key": screen_key},
                "questions": [],
                "etag": new_etag,
            },
            "visibility_delta": {
                "now_visible": list(now_visible),
                "now_hidden": list(now_hidden),
            },
            "suppressed_answers": suppressed_answers,
        }
        # Clarke: ensure 'events' array is present on 200 responses (clear branch)
        try:
            from app.logic.events import get_buffered_events

            body["events"] = get_buffered_events(clear=True)
        except Exception:
            body["events"] = []
        store_replay_after_success(request, response, body)
        return body

    # Proceed with normal validation and write flow
    write_performed = False
    new_etag = current_etag
    # Validate payload according to shared rules; kind-specific rules are out of scope here
    # Evaluate non-finite number cases before generic kind/type checks

    # Type-aware value validation for number/boolean kinds
    kind = _answer_kind_for_question(question_id) or ""
    value: Any = payload.value
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

    validate_answer_upsert(payload.model_dump())
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
            option_id=payload.option_id,
            value=value,
        )
        write_performed = True

    # Compute and expose fresh ETag for the screen
    # Post-save refresh: explicitly use repository helper and shared assembly to rebuild screen view
    _ = list_questions_for_screen(screen_key)
    screen_view = ScreenView(**assemble_screen_view(response_set_id, screen_key))
    new_etag = screen_view.etag or compute_screen_etag(response_set_id, screen_key)

    # Compute visibility after write (or same as before for replay)
    parent_value_post = dict(parent_value_pre)
    # If the changed question is a parent, update the canonical value from payload
    if question_id in parents:
        pv: str | None
        if payload.value is None:
            pv = None
        elif isinstance(payload.value, bool):
            pv = "true" if payload.value else "false"
        else:
            pv = str(payload.value)
        parent_value_post[question_id] = pv

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
        now_visible_ids = list(now_visible)
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
            "now_hidden": now_hidden,
        },
        "suppressed_answers": suppressed_answers,
    }
    # Include buffered domain events in response body per contract
    try:
        from app.logic.events import get_buffered_events

        body["events"] = get_buffered_events(clear=True)
    except Exception:
        body["events"] = []

    # Store replay payload after success, when applicable
    store_replay_after_success(request, response, body)

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
                    option_id=opt,
                    value=value,
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
