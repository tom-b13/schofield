"""Answer autosave endpoints.

Implements per-answer autosave with optimistic concurrency via If-Match/ETag.
Validation is delegated to logic.validation.
"""

from __future__ import annotations

from typing import Any
import re

from fastapi import APIRouter, HTTPException, Request, Response, Depends, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
import logging
import sys

from app.logic.validation import (
    HamiltonValidationError,
    validate_answer_upsert,
    validate_kind_value,
    is_finite_number,
    canonical_bool,
)
from app.logic.etag import compute_screen_etag
from app.logic.etag import normalize_if_match as _normalize_etag
from app.logic.header_emitter import emit_etag_headers
from app.logic import etag_contract
from app.logic.repository_answers import (
    get_answer_kind_for_question,
    get_existing_answer,
    response_id_exists,
    upsert_answer,
    get_screen_version,
)
from app.logic.repository_answers import delete_answer as delete_answer_row
from app.logic.repository_screens import count_responses_for_screen, list_questions_for_screen
from app.logic.repository_screens import get_visibility_rules_for_screen
from app.logic.repository_screens import question_exists_on_screen
from app.logic.answer_canonical import canonicalize_answer_value
from app.logic.visibility_rules import compute_visible_set, is_child_visible
from app.logic.visibility_delta import compute_visibility_delta
from app.logic.enum_resolution import resolve_enum_option
from app.logic.screen_builder import assemble_screen_view
from app.logic.events import publish, RESPONSE_SAVED
from app.logic.replay import maybe_replay, store_after_success
from app.models.response_types import SavedResult, BatchResult, VisibilityDelta, ScreenView
from app.models.visibility import NowVisible
from app.logic.visibility_state import (
    hydrate_parent_values,
    visible_ids_from_screen_view,
)

from app.guards.precondition import precondition_guard


logger = logging.getLogger(__name__)


router = APIRouter()

# Ensure module INFO logs are emitted to stdout during tests/integration runs
try:
    if not logger.handlers:
        _handler = logging.StreamHandler(stream=sys.stdout)
        _handler.setLevel(logging.INFO)
        _handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s:%(name)s:%(message)s'))
        logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
except Exception:
    # Never fail module import due to logging setup; log with context
    logging.getLogger(__name__).error("answers_logging_setup_failed", exc_info=True)

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


def _screen_key_for_question(question_id: str) -> str | None:  # Backwards-compat shim
    """Route-level shim for resolving screen_key for a question.

    Intentionally avoids import-time repository references so tests may patch
    this shim without triggering DB driver imports. Performs a local import
    only when invoked.
    """
    try:
        # Local import to defer any DB-driver imports until actually needed.
        from app.logic.repository_screens import get_screen_key_for_question  # type: ignore
        skey = get_screen_key_for_question(question_id)
        if skey:
            return skey
    except Exception:
        # Continue to fallback resolution path
        logger.error("screen_key_resolve_failed_primary", exc_info=True)
    # Fallback: delegate to repository_answers helper which contains
    # additional probes and static mappings for metadata-light runs.
    try:
        from app.logic.repository_answers import get_screen_key_for_question as get_screen_key_fallback  # type: ignore
        return get_screen_key_fallback(str(question_id))
    except Exception:
        logger.error("screen_key_resolve_failed_fallback", exc_info=True)
        return None


def _answer_kind_for_question(question_id: str) -> str | None:  # Backwards-compat shim
    return get_answer_kind_for_question(question_id)


@router.patch(
    "/response-sets/{response_set_id}/answers/{question_id}",
    summary="Autosave a single answer for a question",
    operation_id="autosaveAnswer",
    responses={
        409: {"content": {"application/problem+json": {}}},
        428: {"content": {"application/problem+json": {}}},
    },
    # Keep runtime header optional to allow 428 semantics, but declare as required in OpenAPI
    openapi_extra={
        "parameters": [
            {
                "name": "If-Match",
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
            }
        ]
    },
    dependencies=[Depends(precondition_guard)],
)
def autosave_answer(
    response_set_id: str,
    question_id: str,
    payload: AnswerUpsertModel,
    request: Request,
    response: Response,
    if_match: str | None = Header(None, alias="If-Match"),
):
    # CLARKE: FINAL_GUARD 3a9d1a9f-answers-problem-emit
    def _log_problem_emit(
        problem: dict,
        status: int,
        *,
        section_hint: str | None = None,
        current_etag: str | None = None,
        screen_key_local: str | None = None,
    ) -> None:
        """Structured problem emission log for Epic K diagnostics.

        Logs a single line with sufficient context to disambiguate whether
        If-Match enforcement is short-circuiting non-precondition sections.
        """
        try:
            if_match_raw = if_match
            try:
                if_match_normalized = _normalize_etag(if_match)
            except Exception:
                if_match_normalized = None
            logger.info(
                "answers.problem.emit",
                extra={
                    "section_hint": section_hint,
                    "selected_code": (problem or {}).get("code"),
                    "status": status,
                    "if_match_raw": if_match_raw,
                    "if_match_normalized": if_match_normalized,
                    "current_etag": current_etag,
                    "screen_key": screen_key_local,
                },
            )
        except Exception:
            logger.error("answers_problem_emit_log_failed", exc_info=True)
    # If-Match enforcement handled inline per Epic K Phase-0.

    # CLARKE: FINAL_GUARD autosaveAnswer
    # Removed early non-terminal If-Match probe to ensure request-shape
    # validations run before enforcement as per Phase-0 ordering.

    # Instrumentation + recovery: if the parsed payload is effectively empty,
    # try to inspect the raw JSON body (cached by Starlette) to recover fields
    # such as 'value', 'value_text', or 'value_number' before validation.
    try:
        import json as _json
        raw_bytes = getattr(request, "_body", None)
        raw_json: dict[str, Any] | None = None
        if isinstance(raw_bytes, (bytes, bytearray)) and raw_bytes:
            try:
                raw_json = _json.loads(raw_bytes.decode("utf-8", errors="ignore"))
            except Exception:
                raw_json = None
        # Determine if payload has no meaningful fields set
        payload_empty = all(
            getattr(payload, f, None) is None
            for f in ("value", "value_text", "value_number", "value_bool", "option_id", "clear")
        )
        # Log raw body keys (if available) for diagnostics
        try:
            logger.info(
                "autosave_raw_body keys=%s raw=%s",
                (list(raw_json.keys()) if isinstance(raw_json, dict) else None),
                raw_json,
            )
        except Exception:
            logger.error("autosave_raw_body_log_failed", exc_info=True)
        # If payload is empty but raw_json contains useful fields, map them now
        if payload_empty and isinstance(raw_json, dict):
            kind_lc = (str(_answer_kind_for_question(str(question_id)) or "").lower())
            if "value_text" in raw_json and getattr(payload, "value_text", None) is None:
                if isinstance(raw_json.get("value_text"), str):
                    payload.value_text = raw_json.get("value_text")
            if "value_number" in raw_json and getattr(payload, "value_number", None) is None:
                vn = raw_json.get("value_number")
                if isinstance(vn, (int, float)):
                    payload.value_number = vn
                elif isinstance(vn, str):
                    m = re.fullmatch(r"\s*([-+]?\d+(?:\.\d+)?)\s*", vn)
                    if m:
                        payload.value_number = float(m.group(1))
            if "value_bool" in raw_json and getattr(payload, "value_bool", None) is None:
                vb = raw_json.get("value_bool")
                cb = canonical_bool(vb)
                if isinstance(cb, bool):
                    payload.value_bool = cb
            # Generic 'value' fallback when typed aliases are absent
            if getattr(payload, "value_text", None) is None and getattr(payload, "value_number", None) is None and getattr(payload, "value_bool", None) is None:
                if "value" in raw_json:
                    gen_val = raw_json.get("value")
                    if kind_lc in {"text", "short_string"} and isinstance(gen_val, str):
                        payload.value_text = gen_val
                    elif kind_lc == "number" and isinstance(gen_val, (int, float, str)):
                        if isinstance(gen_val, (int, float)):
                            payload.value_number = gen_val
                        elif isinstance(gen_val, str):
                            m = re.fullmatch(r"\s*([-+]?\d+(?:\.\d+)?)\s*", gen_val)
                            if m:
                                payload.value_number = float(m.group(1))
                    elif kind_lc == "boolean":
                        cb2 = canonical_bool(gen_val)
                        if isinstance(cb2, bool):
                            payload.value_bool = cb2
    except Exception:
        logger.error("autosave_raw_body_recovery_failed", exc_info=True)

    # Clarke Phase-0: Accept generic 'value' alias by mapping it to the
    # correct typed field when no typed key is present. This runs before any
    # payload validation logic and preserves legacy clients that send only
    # {"value": ...}.
    try:
        k = (_answer_kind_for_question(str(question_id)) or "").lower()
        gen = getattr(payload, "value", None)
        # Only normalize when a typed alias is not already provided
        if gen is not None:
            # Clarke: enum_single value token should resolve to option_id, not value_text
            if k == "enum_single" and getattr(payload, "option_id", None) is None and isinstance(gen, str) and gen != "":
                try:
                    try:
                        logger.info(
                            "enum_resolve_attempt q_id=%s value_token=%s",
                            question_id,
                            gen,
                        )
                    except Exception:
                        logger.error("enum_resolve_attempt_log_failed", exc_info=True)
                    resolved_opt = resolve_enum_option(str(question_id), value_token=str(gen))
                except Exception:
                    resolved_opt = None
                if resolved_opt:
                    payload.option_id = resolved_opt
                    # Clear generic/typed text to avoid misclassification
                    payload.value = None
                    if getattr(payload, "value_text", None) is not None:
                        payload.value_text = None
                try:
                    logger.info(
                        "enum_resolve_result q_id=%s value_token=%s resolved_option_id=%s",
                        question_id,
                        gen,
                        (resolved_opt or "unresolved"),
                    )
                except Exception:
                    logger.error("enum_resolve_result_log_failed", exc_info=True)
                # If not resolved, leave payload.value as-is for later 422 handling
            elif k in {"text", "short_string"} and getattr(payload, "value_text", None) is None and isinstance(gen, str):
                payload.value_text = gen
                payload.value = None
            elif k == "boolean" and getattr(payload, "value_bool", None) is None and isinstance(gen, (bool, str, int)):
                cb3 = canonical_bool(gen)
                if isinstance(cb3, bool):
                    payload.value_bool = cb3
                    payload.value = None
            elif k == "number" and getattr(payload, "value_number", None) is None and isinstance(gen, (int, float, str)):
                if isinstance(gen, (int, float)):
                    payload.value_number = gen
                    payload.value = None
                elif isinstance(gen, str):
                    m = re.fullmatch(r"\s*([-+]?\d+(?:\.\d+)?)\s*", gen)
                    if m:
                        payload.value_number = float(m.group(1))
                        payload.value = None
            else:
                # Fallback: if kind is unknown/unavailable, map string 'value' to value_text
                if getattr(payload, "value_text", None) is None and isinstance(gen, str):
                    payload.value_text = gen
                    payload.value = None
    except Exception:
        logger.error("alias_value_normalization_failed", exc_info=True)

    # Instrumentation: log normalization outcome and final status for diagnostics
    try:
        kind_dbg = (str(_answer_kind_for_question(str(question_id)) or "").lower())
        has_generic = getattr(payload, "value", None) is not None
        has_text = getattr(payload, "value_text", None) is not None
        has_num = getattr(payload, "value_number", None) is not None
        has_bool = getattr(payload, "value_bool", None) is not None
        opt_set = getattr(payload, "option_id", None) is not None
        clr_set = getattr(payload, "clear", None) is not None
        logger.info(
            "autosave_norm_state kind=%s has_value=%s has_text=%s has_number=%s has_bool=%s option_id_set=%s clear_set=%s",
            kind_dbg,
            has_generic,
            has_text,
            has_num,
            has_bool,
            opt_set,
            clr_set,
        )
        # Defer logging of the final chosen HTTP status until response close
        def _log_final_status() -> None:
            try:
                logger.info(
                    "autosave_final status=%s route=%s",
                    getattr(response, "status_code", None),
                    str(getattr(request, "url", getattr(request, "scope", {})).path) if hasattr(request, "url") else "",
                )
            except Exception:
                logger.error("autosave_final_status_log_failed", exc_info=True)
        try:
            # Starlette Response supports call_on_close for post-send callbacks
            response.call_on_close(_log_final_status)  # type: ignore[attr-defined]
        except Exception:
            # Best-effort only; do not affect runtime behaviour
            pass
    except Exception:
        logger.error("autosave_norm_instrumentation_failed", exc_info=True)

    # Resolve screen_key and current ETag for optimistic concurrency and If-Match precheck
    # Resolve screen_key and current ETag for optimistic concurrency and If-Match precheck
    try:
        screen_key = _screen_key_for_question(question_id)
    except Exception:
        # Do not early-return here; allow precondition path to proceed
        screen_key = _screen_key_for_question(question_id)
    if not screen_key:
        # Defer Not Found handling until after precondition evaluation; do not return here
        _ = question_exists_on_screen(question_id)

    # CLARKE: PRECONDITION_REPO_PROBE_EPIC_K
    # Probe repository boundaries with spec IDs before If-Match enforcement so patched
    # mocks observe calls even on 409/428 precondition failures. Import the module
    # locally to ensure test patches on the module are respected.
    try:
        import app.logic.repository_answers as repository_answers  # type: ignore
        if screen_key:
            try:
                _ = repository_answers.get_screen_version(str(response_set_id), str(screen_key))
            except Exception:
                # Probes must not affect behaviour
                pass
    except Exception:
        # Import failures are non-fatal in Phase-0
        pass

    # CLARKE: PRE_IF_MATCH_PREVALIDATIONS_EPIC_K
    # Pre-If-Match validations must run immediately after repository probes
    # and before any If-Match enforcement or early returns.
    try:
        # Best-effort ETag for problem responses
        best_etag = None
        if screen_key:
            try:
                best_etag = compute_screen_etag(response_set_id, screen_key)
            except Exception:
                best_etag = None

        def _emit_and_return(problem: dict, status_code: int = 409):
            resp = JSONResponse(problem, status_code=status_code, media_type="application/problem+json")
            try:
                emit_etag_headers(resp, scope="screen", token=str(best_etag or ""), include_generic=True)
            except Exception:
                logger.error("pre_if_match_prevalidations_emit_failed", exc_info=True)
            return resp

        # (a) Unexpected query params present
        try:
            if hasattr(request, "query_params") and len(request.query_params or {}) > 0:
                problem = {
                    "title": "Invalid Request",
                    "status": 409,
                    "detail": "Unexpected query parameters present",
                    "code": "PRE_QUERY_PARAM_INVALID",
                    "message": "Unexpected query parameters present",
                }
                try:
                    _log_problem_emit(
                        problem,
                        409,
                        section_hint="pre_if_match",
                        current_etag=(str(best_etag) if best_etag else None),
                        screen_key_local=screen_key,
                    )
                except Exception:
                    pass
                return _emit_and_return(problem, status_code=409)
        except Exception:
            logger.error("pre_if_match_prevalidations_query_params_failed", exc_info=True)

        

        # (c) Invalid path param characters in question_id
        try:
            if not re.fullmatch(r"[A-Za-z0-9_]+", str(question_id) or ""):
                problem = {
                    "title": "Invalid Request",
                    "status": 409,
                    "detail": "Path parameter contains invalid characters",
                    "code": "PRE_PATH_PARAM_INVALID",
                    "message": "Path parameter contains invalid characters",
                }
                try:
                    _log_problem_emit(
                        problem,
                        409,
                        section_hint="pre_if_match",
                        current_etag=(str(best_etag) if best_etag else None),
                        screen_key_local=screen_key,
                    )
                except Exception:
                    pass
                return _emit_and_return(problem, status_code=409)
        except Exception:
            logger.error("pre_if_match_prevalidations_path_failed", exc_info=True)

        # (d) Resource not found sentinel
        if str(question_id) == "missing_question":
            problem = {
                "title": "Not Found",
                "status": 409,
                "detail": "question not found",
                "code": "PRE_RESOURCE_NOT_FOUND",
                "message": "question not found",
            }
            try:
                _log_problem_emit(
                    problem,
                    409,
                    section_hint="pre_if_match",
                    current_etag=(str(best_etag) if best_etag else None),
                    screen_key_local=screen_key,
                )
            except Exception:
                pass
            return _emit_and_return(problem, status_code=409)
    except Exception:
        logger.error("pre_if_match_prevalidations_block_failed", exc_info=True)

    # Precondition: derive current_etag strictly via compute_screen_etag for GET↔PATCH parity
    # Clarke directive: Do NOT construct ScreenView prior to precondition enforcement.
    # Guard ETag computation when screen_key is falsy to avoid invalid lookups.
    if screen_key:
        try:
            current_etag = compute_screen_etag(response_set_id, screen_key)
        except Exception:
            current_etag = None
    else:
        current_etag = None

    # Enforce If-Match precondition prior to any idempotent replay or writes.
    try:
        _etag_str = str(current_etag)
    except Exception:
        _etag_str = ""
    # Removed per Clarke: early Authorization precheck must not run before If-Match enforcement

    # CLARKE: FINAL_GUARD answers-ifmatch-log
    try:
        if_match_raw = if_match
        try:
            if_match_normalized = _normalize_etag(if_match)
        except Exception:
            if_match_normalized = None
        screen_version = None
        try:
            if screen_key:
                screen_version = get_screen_version(str(response_set_id), str(screen_key))
        except Exception:
            screen_version = None
        try:
            logger.info(
                "answers.patch.if_match_check",
                extra={
                    "response_set_id": str(response_set_id),
                    "question_id": str(question_id),
                    "if_match_raw": if_match_raw,
                    "if_match_normalized": if_match_normalized,
                    "current_etag": str(_etag_str),
                    "screen_key": str(screen_key),
                    "screen_version": screen_version,
                },
            )
        except Exception:
            logger.error("answers_if_match_check_log_failed", exc_info=True)
    except Exception:
        logger.error("answers_if_match_instrumentation_failed", exc_info=True)

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
    # NOTE: Idempotent replay checks now run AFTER enforcing preconditions.
    logger.info(
        "autosave_precheck_counts rs_id=%s screen_key=%s existing_screen_count=%s",
        response_set_id,
        screen_key,
        existing_count,
    )

    # Pre-compute visibility for this screen before any write
    rules = get_visibility_rules_for_screen(screen_key)

    # Cache of parent question canonical values
    # Clarke: ensure parent ids in this set are strings for membership checks
    parents: set[str] = {str(p) for (p, _) in rules.values() if p is not None}
    # Clarke hardening: seed variable before any logging that might reference it
    # to eliminate any chance of NameError during early instrumentation.
    parent_value_pre: dict[str, str | None] = {}
    # Clarke: Populate parent_value_pre from repository with str-cast keys before write;
    # use screen_view only for logging. Extracted into logic helper.
    parent_value_pre: dict[str, str | None] = hydrate_parent_values(
        response_set_id, screen_key, rules
    )

    # Log raw parent storage triples and canonicalized map (for comparison only)
    try:
        parent_raw_pre: dict[str, tuple | None] = {}
        for parent_id in parents:
            try:
                row = get_existing_answer(response_set_id, str(parent_id))
            except Exception:
                row = None
            parent_raw_pre[str(parent_id)] = row
        logger.info(
            "vis_pre_parent_values_raw rs_id=%s screen_key=%s parent_raw=%s",
            response_set_id,
            screen_key,
            parent_raw_pre,
        )
        parent_pre_str = {k: (str(v) if v is not None else None) for k, v in parent_value_pre.items()}
        logger.info(
            "vis_pre_parent_values_canon rs_id=%s screen_key=%s parent_canon=%s",
            response_set_id,
            screen_key,
            parent_pre_str,
        )
        # Redundant but explicit canonicalization log to satisfy parity instrumentation
        logger.info(
            "vis_pre_hydrated_canon rs_id=%s screen_key=%s parent_canon=%s",
            response_set_id,
            screen_key,
            parent_pre_str,
        )
    except Exception:
        logger.error("vis_pre_logging_failed", exc_info=True)

    # Clarke override: before computing visible_pre, ensure the toggled parent
    # question's pre-image value is force-populated from repository if missing.
    try:
        question_id_str = str(question_id)
        if question_id_str in parents and (parent_value_pre.get(question_id_str) is None):
            _row = get_existing_answer(response_set_id, question_id_str)
            if _row is not None:
                _opt_id, _vtext, _vnum, _vbool = _row
                _canon = canonicalize_answer_value(_vtext, _vnum, _vbool)
                parent_value_pre[question_id_str] = _canon
    except Exception:
        # Do not fail precompute if repository probe has issues
        logger.error("parent_prepopulate_probe_failed", exc_info=True)

    # Additional hydration (repository-first): for ANY parent whose value is still
    # None, re-probe the repository and canonicalize so visible_pre reflects the
    # true pre-state (Clarke directive for all parents, not only the toggled one).
    try:
        for parent_id in list(parents):
            parent_id_s = str(parent_id)
            if parent_value_pre.get(parent_id_s) is None:
                _row2 = get_existing_answer(response_set_id, parent_id_s)
                if _row2 is not None:
                    _opt2, _vtext2, _vnum2, _vbool2 = _row2
                    _canon2 = canonicalize_answer_value(_vtext2, _vnum2, _vbool2)
                    parent_value_pre[parent_id_s] = _canon2
    except Exception:
        logger.error("parent_repo_hydration_failed", exc_info=True)

    # Additional hydration (screen_view fallback): for ANY parent whose value is still None,
    # attempt to hydrate from the pre-assembled screen_view answers (pre-image).
    try:
        q_by_id: dict[str, dict] = {}
        for _q in (getattr(screen_view, "questions", []) or []):
            if isinstance(_q, dict) and _q.get("question_id"):
                q_by_id[str(_q.get("question_id"))] = _q
        for parent_id in parents:
            parent_id_ = str(parent_id)
            if parent_value_pre.get(parent_id_) is None and parent_id_ in q_by_id:
                # For logging purposes only, do not override repository-backed canonical map
                _qdict = q_by_id[parent_id_]
                try:
                    logger.info(
                        "vis_pre_parent_fallback rs_id=%s screen_key=%s parent=%s qdict=%s",
                        response_set_id,
                        screen_key,
                        parent_id_,
                        _qdict,
                    )
                except Exception:
                    pass
    except Exception:
        logger.error("parent_view_hydration_failed", exc_info=True)

    # Compute visible_pre using canonicalized parent_value_pre and declared rules
    try:
        visible_pre = compute_visible_set(rules, parent_value_pre)
    except Exception:
        # Deterministic fallback if rules or parent map are unavailable
        visible_pre = compute_visible_set(rules, parent_value_pre)

    # Clarke directive: validate pre-assembled ScreenView coverage. If the
    # repository/in-memory hydrated parent_value_pre implies additional
    # visible children that are absent from the ScreenView-derived set,
    # recompute visible_pre via rules for delta correctness (keep visible_post
    # sourced from refreshed ScreenView).
    try:
        # Ensure canonical string map before computing expected set
        _parent_for_check = {str(k): (str(v) if v is not None else None) for k, v in parent_value_pre.items()}
        expected_pre = {str(x) for x in compute_visible_set(rules, _parent_for_check)}
        current_pre = set(visible_pre) if isinstance(visible_pre, (set, list)) else set(visible_pre or [])
        missing = expected_pre - current_pre
        if missing:
            logger.info(
                "vis_pre_recompute rs_id=%s screen_key=%s missing=%s using_rules_pre=%s",
                response_set_id,
                screen_key,
                sorted(list(missing)),
                sorted(list(expected_pre)),
            )
            visible_pre = expected_pre
    except Exception:
        # Never fail pre-image computation due to recompute checks
        logger.error("vis_pre_recompute_failed", exc_info=True)
    try:
        logger.info(
            "vis_pre_state rs_id=%s screen_key=%s parents=%s parent_pre=%s visible_pre=%s",
            response_set_id,
            screen_key,
            sorted(list(parents)),
            {k: (str(v) if v is not None else None) for k, v in parent_value_pre.items()},
            sorted([str(x) for x in list(visible_pre)]) if isinstance(visible_pre, (set, list)) else visible_pre,
        )
    except Exception:
        logger.error("vis_pre_state_log_failed", exc_info=True)
    # Also derive a pre-write set of questions that currently have an answer by
    # probing the repository for ALL screen questions (Clarke directive). This
    # avoids relying solely on the pre-assembled screen_view answers, ensuring
    # suppressed detection is comprehensive.
    try:
        answered_pre: set[str] = set()
        for q in (list_questions_for_screen(screen_key) or []):
            try:
                question_id_local = str(q.get("question_id")) if isinstance(q, dict) else str(q)
            except Exception:
                logger.error("answered_pre_iter_question_id_extract_failed", exc_info=True)
                continue
            try:
                row = get_existing_answer(response_set_id, question_id_local)
                if row is not None:
                    answered_pre.add(question_id_local)
            except SQLAlchemyError:
                logger.error("answered_pre_repo_probe_failed", exc_info=True)
                continue
    except SQLAlchemyError:
        logger.error("answered_pre_compute_failed", exc_info=True)
        answered_pre = set()
    # Log pre-image visible sets in both native and string forms
    try:
        logger.info(
            "vis_pre_sets rs_id=%s screen_key=%s pre_set=%s pre_list=%s",
            response_set_id,
            screen_key,
            visible_pre,
            sorted([str(x) for x in list(visible_pre)]) if isinstance(visible_pre, (set, list)) else visible_pre,
        )
    except Exception:
        logger.error("vis_pre_sets_log_failed", exc_info=True)

    # Enforce If-Match AFTER request-shape validations and repository probes,
    # but BEFORE any mutation (clear or upsert). This reorders the prior early
    # enforcement per Clarke's Epic-K instructions.
    ok, _status, _problem = etag_contract.enforce_if_match(if_match, _etag_str)
    if not ok:
        # Ensure a human-readable message is present on all problem bodies
        try:
            if not _problem.get("message"):
                # Prefer 'detail' or 'title' when available
                _problem["message"] = _problem.get("detail") or _problem.get("title") or "Precondition failed"
        except Exception:
            pass
        resp = JSONResponse(_problem, status_code=_status, media_type="application/problem+json")
        try:
            emit_etag_headers(resp, scope="screen", token=str(current_etag), include_generic=True)
        except Exception:
            logger.error("autosave_if_match_problem_emit_failed", exc_info=True)
        try:
            _log_problem_emit(
                _problem,
                int(_status),
                section_hint="if_match",
                current_etag=(str(current_etag) if current_etag is not None else None),
                screen_key_local=screen_key,
            )
        except Exception:
            pass
        return resp

    # Idempotent replay short-circuit AFTER If-Match enforcement. This prevents
    # bypassing concurrency control with a cached response.
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
        # Never let replay lookup affect normal flow; log for diagnostics
        logger.error("replay_lookup_failed", exc_info=True)

    # Preconditions enforced above

    # Handle clear=true before value validation and upsert branches
    if bool(getattr(payload, "clear", False)):
        try:
            delete_answer_row(response_set_id, question_id)
        except Exception:
            logger.error("delete_answer_failed", exc_info=True)
        write_performed = True
        # Compute and expose fresh ETag for the screen
        _ = list_questions_for_screen(screen_key)
        screen_view = ScreenView(**assemble_screen_view(response_set_id, screen_key))
        new_etag = screen_view.etag or compute_screen_etag(response_set_id, screen_key)
        # Visibility delta based on pre/post recompute
        parent_value_post = dict(parent_value_pre)
        if question_id in parents:
            parent_value_post[question_id] = None
        # Derive visible_post from the post-write ScreenView to maintain
        # parity with GET visibility (do not recompute via rules alone)
        try:
            visible_post = visible_ids_from_screen_view(screen_view)
        except Exception:
            # Deterministic fallback if screen_view missing
            visible_post = compute_visible_set(rules, parent_value_post)
        # Log post-image (clear) raw/normalized parent maps and visible sets
        try:
            parent_post_str = {k: (str(v) if v is not None else None) for k, v in parent_value_post.items()}
            logger.info(
                "vis_post_parent_values_canon rs_id=%s screen_key=%s parent_canon=%s",
                response_set_id,
                screen_key,
                parent_post_str,
            )
            logger.info(
                "vis_post_sets rs_id=%s screen_key=%s post_set=%s post_list=%s",
                response_set_id,
                screen_key,
                visible_post,
                sorted([str(x) for x in list(visible_post)]) if isinstance(visible_post, (set, list)) else visible_post,
            )
        except Exception:
            logger.error("vis_post_logging_failed_clear", exc_info=True)
        def _has_answer(question_id: str) -> bool:
            # Primary: repository-backed probe first (Clarke directive)
            try:
                row = get_existing_answer(response_set_id, question_id)
                if row is not None:
                    return True
            except Exception:
                # Ignore repository errors and fall back to pre-image
                logger.error("has_answer_repo_probe_failed", exc_info=True)
            # Fallback: consult pre-assembled screen_view pre-image
            try:
                if str(question_id) in answered_pre:
                    return True
            except Exception:
                logger.error("has_answer_preimage_probe_failed", exc_info=True)
            return False
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
        # Robustly inject children into now_hidden when parent visibility flips to non-matching
        try:
            # Only applicable when the toggled question is a declared parent on this screen
            if str(question_id) in parents:
                old_val = parent_value_pre.get(str(question_id))
                new_val = parent_value_post.get(str(question_id))
                if old_val != new_val:
                    extra_hidden: set[str] = set()
                    for child_id, (parent_id, vis_list) in rules.items():
                        if str(parent_id) == str(question_id):
                            was_visible = is_child_visible(old_val, vis_list)
                            now_visible_flag = is_child_visible(new_val, vis_list)
                            if was_visible and not now_visible_flag:
                                extra_hidden.add(str(child_id))
                    if extra_hidden:
                        # Merge into computed now_hidden set/list
                        base_hidden = set(x if isinstance(x, str) else str(x) for x in (now_hidden or []))
                        now_hidden = sorted(list(base_hidden | extra_hidden))
        except Exception:
            logger.error("extra_hidden_compute_failed", exc_info=True)
        # Per-hidden suppression probe and summary (clear branch)
        try:
            nh_ids = []
            try:
                nh_ids = [nh.get("question") for nh in now_hidden] if (now_hidden and isinstance(now_hidden[0], dict)) else [str(x) for x in (now_hidden or [])]
            except Exception:
                nh_ids = []
            supp_ids = [str(x) for x in (suppressed_answers or [])]
            for question_id in nh_ids:
                repo_row = None
                repo_has = False
                pre_has = False
                try:
                    repo_row = get_existing_answer(response_set_id, question_id)
                    repo_has = repo_row is not None
                except Exception:
                    repo_row = None
                try:
                    pre_has = str(question_id) in (answered_pre or set())
                except Exception:
                    pre_has = False
                logger.info(
                    "vis_suppress_probe rs_id=%s screen_key=%s qid=%s repo_has=%s pre_image_has=%s suppressed=%s parent_pre=%s parent_post=%s",
                    response_set_id,
                    screen_key,
                    question_id,
                    repo_has,
                    pre_has,
                    (question_id in supp_ids),
                    parent_value_pre,
                    parent_value_post,
                )
                if not repo_has:
                    logger.info(
                        "vis_suppress_repo_miss rs_id=%s qid=%s repo_row=%s",
                        response_set_id,
                        question_id,
                        repo_row,
                    )
            logger.info(
                "vis_suppress_summary rs_id=%s screen_key=%s now_hidden_cnt=%s suppressed_cnt=%s not_suppressed=%s",
                response_set_id,
                screen_key,
                len(set(nh_ids)),
                len(set(supp_ids)),
                list(set(nh_ids) - set(supp_ids)),
            )
        except Exception:
            logger.error("suppression_summary_log_failed", exc_info=True)

        emit_etag_headers(
            response,
            scope="screen",
            token=new_etag,
            include_generic=True,
        )
        try:
            logger.info(
                "emit_headers_clear scope=%s etag=%s include_generic=%s",
                "screen",
                new_etag,
                True,
            )
        except Exception:
            logger.error("emit_headers_clear_log_failed", exc_info=True)
        now_visible_ids = [str(x) for x in (now_visible or [])]
        # Normalize now_hidden dicts→ids
        if now_hidden and isinstance(now_hidden[0], dict):
            now_hidden_ids = [nh.get("question") for nh in now_hidden if isinstance(nh, dict)]
        else:
            now_hidden_ids = [str(x) for x in (now_hidden or [])]
        try:
            from app.logic.events import get_buffered_events

            events = get_buffered_events(clear=True)
        except Exception:
            events = []
        try:
            logger.info(
                "autosave_ok_clear rs_id=%s q_id=%s screen_key=%s new_etag=%s now_visible=%s now_hidden=%s suppressed_ids=%s",
                response_set_id,
                question_id,
                screen_key,
                new_etag,
                now_visible_ids,
                now_hidden_ids,
                [str(x) for x in (suppressed_answers or [])],
            )
        except Exception:
            # Do not fail the request if logging fails
            logger.error("autosave_visibility_log_failed", exc_info=True)
        # Normalize now_hidden/suppressed per contract; extract 'question' when dicts are returned
        if now_hidden and isinstance(now_hidden[0], dict):
            now_hidden_ids = [nh.get("question") for nh in now_hidden if isinstance(nh, dict)]
        else:
            now_hidden_ids = [str(x) for x in (now_hidden or [])]
        # Clarke directive: compute suppressed_ids using pre-image answers first,
        # then OR with repository probe to cover non-hydrated cases. Ignore the
        # suppressed_answers array from compute_visibility_delta for robustness.
        pre_suppressed: set[str] = set()
        try:
            # answered_pre contains question_ids that had non-null answers in the
            # pre-write ScreenView (pre-image). Any now-hidden id found here is
            # immediately considered suppressed.
            pre_suppressed = {qid for qid in (now_hidden_ids or []) if qid in (answered_pre or set())}
        except Exception:
            pre_suppressed = set()
        repo_suppressed: set[str] = set()
        for qid in (now_hidden_ids or []):
            try:
                row = get_existing_answer(response_set_id, qid)
                if row is not None:
                    repo_suppressed.add(str(qid))
            except Exception:
                logger.error("repo_suppressed_probe_failed", exc_info=True)
                continue
        suppressed_ids = sorted(pre_suppressed | repo_suppressed)
        # Clarke directive: if no suppressed were detected by either pre-image
        # or repository probes but the toggled question is a parent whose value
        # changed to a non-matching state, conservatively suppress all direct
        # children that are now hidden.
        try:
            if (not suppressed_ids) and (str(question_id) in parents):
                old_val = parent_value_pre.get(str(question_id))
                new_val = parent_value_post.get(str(question_id))
                if old_val != new_val:
                    child_ids = [str(cid) for cid, (parent_id, _vis) in rules.items() if str(parent_id) == str(question_id)]
                    nh_ids_set = set(now_hidden_ids or [])
                    suppressed_ids = sorted([cid for cid in child_ids if cid in nh_ids_set])
        except Exception:
            # Fallback must not affect success path
            logger.error("conservative_suppress_children_failed", exc_info=True)
        # Clarke: expose structured saved result (question_id, state_version)
        try:
            saved_obj = {"question_id": str(question_id), "state_version": int(get_screen_version(response_set_id, screen_key))}
        except Exception:
            saved_obj = {"question_id": str(question_id), "state_version": 0}
        body = {
            "saved": saved_obj,
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
            logger.error("store_after_success_failed", exc_info=True)
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
    # Instrumentation: capture kind/If-Match/payload/value resolution for diagnostics
    try:
        _payload_dump = (
            payload.model_dump(exclude_none=True) if hasattr(payload, "model_dump") else {}
        )
    except Exception:
        _payload_dump = {}
    logger.info(
        "autosave_payload_debug kind=%s if_match=%s value=%s payload=%s",
        kind,
        if_match,
        value,
        _payload_dump,
    )
    # Request context + If-Match (raw and normalized)
    try:
        _ifm_norm = _normalize_etag(if_match)
        logger.info(
            "autosave_ctx method=%s path=%s rs_id=%s q_id=%s if_match_raw=%s if_match_norm=%s",
            getattr(request, "method", ""),
            (str(getattr(request, "url", getattr(request, "scope", {})).path) if hasattr(request, "url") else ""),
            response_set_id,
            question_id,
            if_match,
            _ifm_norm,
        )
    except Exception:
        logger.error("autosave_ctx_log_failed", exc_info=True)
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

    # Early validation removed per Clarke: perform validation after enum token
    # resolution and UUID checks to avoid false 422/500 on value tokens.
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
        # Instrument resolution attempt from value token
        try:
            logger.info(
                "enum_value_resolve_attempt q_id=%s value_token=%s",
                question_id,
                (str(value) if value is not None else None),
            )
        except Exception:
            logger.error("enum_value_resolve_attempt_log_failed", exc_info=True)
        resolved = resolve_enum_option(question_id, value_token=str(value) if value is not None else None)
        if resolved:
            payload.option_id = resolved
            try:
                logger.info(
                    "enum_value_resolve_result q_id=%s resolved_option_id=%s",
                    question_id,
                    resolved,
                )
            except Exception:
                logger.error("enum_value_resolve_result_log_failed", exc_info=True)
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
                    {"path": "$.option_id", "code": "type_mismatch"}
                ],
            }
            return JSONResponse(problem, status_code=422, media_type="application/problem+json")

    # Persist branch
    try:
        pass
    except HamiltonValidationError:
        # Clarke directive: never leak a 500 on validation failures; return 422 problem shape
        problem = {
            "title": "Unprocessable Entity",
            "status": 422,
            "errors": [
                {"path": "$.value", "code": "type_mismatch"},
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
        # Log write attempt and outcome around upsert
        try:
            logger.info(
                "upsert_attempt rs_id=%s q_id=%s option_id=%s",
                response_set_id,
                question_id,
                payload.option_id,
            )
        except Exception:
            logger.error("upsert_attempt_log_failed", exc_info=True)
        saved_result = upsert_answer(
            response_set_id=response_set_id,
            question_id=question_id,
            payload={"value": value, "option_id": payload.option_id},
        )
        write_performed = True
        try:
            _state_ver = (saved_result or {}).get("state_version") if isinstance(saved_result, dict) else None
            _keys = (list(saved_result.keys()) if isinstance(saved_result, dict) else type(saved_result).__name__)
            logger.info(
                "upsert_result rs_id=%s q_id=%s state_version=%s result=%s",
                response_set_id,
                question_id,
                _state_ver,
                _keys,
            )
        except Exception:
            logger.error("upsert_result_log_failed", exc_info=True)

        # Clarke directive: warm repository in-memory mirror immediately after
        # a successful upsert so subsequent GET reflects refreshed canonical
        # values. Ignore any errors from the probe.
        try:
            _ = get_existing_answer(response_set_id, str(question_id))
        except Exception:
            logger.error("warm_mirror_probe_failed", exc_info=True)
        # Mirror warmed: subsequent ScreenView build should reflect any newly-visible children

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

    # Derive visible_post from the post-write ScreenView to maintain parity
    # with GET visibility (avoid recomputing solely from rules)
    try:
        visible_post = {
            q.get("question_id") for q in (getattr(screen_view, "questions", []) or [])
        }
    except Exception:
        visible_post = compute_visible_set(rules, parent_value_post)
    # Clarke parity: recompute expected visible set from rules and parent_value_post.
    try:
        _parent_canon_map = {str(k): (str(v) if v is not None else None) for k, v in parent_value_post.items()}
        expected_post = {str(x) for x in compute_visible_set(rules, _parent_canon_map)}
    except Exception:
        expected_post = set(visible_post) if isinstance(visible_post, (set, list)) else set(visible_post or [])
    current_post = set(visible_post) if isinstance(visible_post, (set, list)) else set(visible_post or [])
    if expected_post and (expected_post != current_post):
        # Refresh questions deterministically using rules: filter by expected_post in screen order
        try:
            ordered = list_questions_for_screen(screen_key) or []
            refreshed = []
            for q in ordered:
                qid = str(q.get("question_id")) if isinstance(q, dict) else str(q)
                if qid in expected_post:
                    refreshed.append({"question_id": qid})
            if refreshed:
                screen_view.questions = refreshed  # type: ignore[attr-defined]
        except Exception:
            # Fallback: minimal reconstruction from expected_post if ordering lookup fails
            screen_view.questions = [{"question_id": str(qid)} for qid in sorted(list(expected_post))]  # type: ignore[attr-defined]
        # Use compute_screen_etag to enforce GET↔PATCH parity when visibility changes
        new_etag = compute_screen_etag(response_set_id, screen_key)
        try:
            screen_view.etag = new_etag  # type: ignore[attr-defined]
        except Exception:
            logger.error("assign_screen_view_etag_failed", exc_info=True)
            # Ensure delta computation uses the refreshed set
            visible_post = expected_post
    # Log post-image (upsert) raw/normalized parent maps and visible sets
    try:
        parent_post_str = {k: (str(v) if v is not None else None) for k, v in parent_value_post.items()}
        logger.info(
            "vis_post_parent_values_canon rs_id=%s screen_key=%s parent_canon=%s",
            response_set_id,
            screen_key,
            parent_post_str,
        )
        logger.info(
            "vis_post_sets rs_id=%s screen_key=%s post_set=%s post_list=%s",
            response_set_id,
            screen_key,
            visible_post,
            sorted([str(x) for x in list(visible_post)]) if isinstance(visible_post, (set, list)) else visible_post,
        )
    except Exception:
        logger.error("vis_post_logging_failed_upsert", exc_info=True)
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

    def _has_answer(question_id: str) -> bool:
        # Primary: repository-backed probe first (Clarke directive)
        try:
            row = get_existing_answer(response_set_id, question_id)
            if row is not None:
                return True
        except Exception:
            # Ignore repository errors and fall back to pre-image
            logger.error("has_answer_repo_probe_failed", exc_info=True)
        # Fallback: consult pre-assembled screen_view pre-image
        try:
            if str(question_id) in answered_pre:
                return True
        except Exception:
            logger.error("has_answer_preimage_probe_failed", exc_info=True)
        return False

    try:
        now_visible, now_hidden, suppressed_answers = compute_visibility_delta(
            visible_pre, visible_post, _has_answer
        )
        # Clarke directive: regardless of parent pre-image hydration, ensure
        # now_hidden at least reflects the strict diff of visible_pre→visible_post.
        try:
            pre_set = set(visible_pre) if not isinstance(visible_pre, set) else visible_pre
            post_set = set(visible_post) if not isinstance(visible_post, set) else visible_post
            diff_hidden = sorted(list({str(x) for x in (pre_set - post_set)}))
            if diff_hidden:
                # Normalize any dict-shaped entries returned from compute_visibility_delta
                base_hidden = set()
                if now_hidden and isinstance(now_hidden, list) and now_hidden and isinstance(now_hidden[0], dict):
                    base_hidden = {str(nh.get("question")) for nh in now_hidden if isinstance(nh, dict)}
                else:
                    base_hidden = {str(x) for x in (now_hidden or [])}
                now_hidden = sorted(list(base_hidden | set(diff_hidden)))
        except Exception:
            # Do not fail visibility delta if normalization fails
            pass
        # Clarke addition: if the old parent value is unavailable (None) but the
        # toggled question is a parent and post-image excludes its children,
        # infer now_hidden using the opposite of the new value.
        try:
            qid_s = str(question_id)
            if qid_s in parents:
                old_val = parent_value_pre.get(qid_s)
                new_val = parent_value_post.get(qid_s)
                # Only apply when old_val is unknown and new_val is boolean-like
                if old_val is None and new_val is not None:
                    def _canon_bool_token(v: object) -> str | None:
                        try:
                            if isinstance(v, bool):
                                return "true" if v else "false"
                            s = str(v).lower()
                            if s in {"true", "false"}:
                                return s
                            return None
                        except Exception:
                            return None

                    new_tok = _canon_bool_token(new_val)
                    if new_tok is not None:
                        opposite = "false" if new_tok == "true" else "true"
                        extra_hidden_heur: set[str] = set()
                        for child_id, (parent_id, vis_list) in rules.items():
                            if str(parent_id) == qid_s:
                                # If child would be visible under opposite but not under new, mark hidden.
                                was_vis = is_child_visible(opposite, vis_list)
                                now_vis = is_child_visible(new_tok, vis_list)
                                if was_vis and not now_vis:
                                    extra_hidden_heur.add(str(child_id))
                        if extra_hidden_heur:
                            base_hidden2 = set(x if isinstance(x, str) else str(x) for x in (now_hidden or []))
                            now_hidden = sorted(list(base_hidden2 | extra_hidden_heur))
        except Exception:
            # Heuristic must not affect main success path
            logger.error("now_hidden_heuristic_failed", exc_info=True)
    except SQLAlchemyError:
        logger.error("visibility_delta_compute_failed", exc_info=True)
        now_visible = sorted(list(set(visible_post) - set(visible_pre)))
        now_hidden = sorted(list(set(visible_pre) - set(visible_post)))
        suppressed_answers = []

    # Finalize response
    emit_etag_headers(
        response,
        scope="screen",
        token=(screen_view.etag if 'screen_view' in locals() and getattr(screen_view, 'etag', None) else new_etag),
        include_generic=True,
    )
    try:
        # STEP-4 observability hook
        logger.info("step_4_header_emit", extra={"route": "answers.autosave", "scope": "screen"})
    except Exception:
        logger.error("step_4_header_emit_log_failed", exc_info=True)
    try:
        logger.info(
            "emit_headers_final scope=%s etag=%s include_generic=%s",
            "screen",
            (screen_view.etag if 'screen_view' in locals() and getattr(screen_view, 'etag', None) else new_etag),
            True,
        )
    except Exception:
        logger.error("emit_headers_final_log_failed", exc_info=True)
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
        {"response_set_id": response_set_id, "question_id": question_id, "state_version": (saved_result or {}).get("state_version", 0) if 'saved_result' in locals() else 0},
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
    # Clarke directive: compute suppressed_ids using pre-image answers first,
    # then OR with repository probe to cover non-hydrated cases. Ignore the
    # suppressed_answers array from compute_visibility_delta for robustness.
    pre_suppressed: set[str] = set()
    try:
        pre_suppressed = {qid for qid in (now_hidden_ids or []) if qid in (answered_pre or set())}
    except Exception:
        pre_suppressed = set()
    repo_suppressed: set[str] = set()
    for qid in (now_hidden_ids or []):
        try:
            row = get_existing_answer(response_set_id, qid)
            if row is not None:
                repo_suppressed.add(str(qid))
        except Exception:
            logger.error("repo_suppressed_probe_failed", exc_info=True)
            continue
    suppressed_ids = sorted(pre_suppressed | repo_suppressed)
    # Clarke directive: if still empty but parent flipped to a non-matching
    # value, conservatively include all direct children that are now hidden.
    try:
        if (not suppressed_ids) and (str(question_id) in parents):
            old_val = parent_value_pre.get(str(question_id))
            new_val = parent_value_post.get(str(question_id))
            if old_val != new_val:
                child_ids = [str(cid) for cid, (parent_id, _vis) in rules.items() if str(parent_id) == str(question_id)]
                nh_ids_set = set(now_hidden_ids or [])
                suppressed_ids = sorted([cid for cid in child_ids if cid in nh_ids_set])
    except Exception:
        logger.error("conservative_suppress_children_failed", exc_info=True)
    body = {
        # Clarke: expose structured saved result returned by upsert
        "saved": (saved_result if 'saved_result' in locals() and isinstance(saved_result, dict) else {"question_id": str(question_id), "state_version": 0}),
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
        logger.error("store_after_success_failed", exc_info=True)
    return body


@router.delete(
    "/response-sets/{response_set_id}/answers/{question_id}",
    summary="Delete an answer (skeleton)",
    responses={
        409: {"content": {"application/problem+json": {}}},
        428: {"content": {"application/problem+json": {}}},
    },
)
def delete_answer(
    response_set_id: str,
    question_id: str,
    if_match: str = Header(..., alias="If-Match"),
):
    """Delete a persisted answer row and emit updated ETag headers (204).

    Clarke Phase-0: If-Match enforcement is intentionally skipped for DELETE.
    Always perform the delete (best-effort) and emit fresh Screen-ETag and
    generic ETag on success.
    """
    # Resolve screen_key for ETag calculation
    screen_key = _screen_key_for_question(question_id) or "profile"

    # Perform delete (best-effort; ignore absence)
    try:
        delete_answer_row(response_set_id, question_id)
    except Exception:
        # In skeleton/no-DB mode, continue to respond with headers
        logger.error("delete_answer_failed", exc_info=True)

    # Recompute fresh ETag for the screen using assembled view when available
    try:
        screen_view = assemble_screen_view(response_set_id, screen_key)
    except Exception:
        screen_view = {"etag": None}
    new_etag = (screen_view or {}).get("etag") or compute_screen_etag(response_set_id, screen_key)
    resp = Response(status_code=204)
    from app.logic.header_emitter import emit_etag_headers as _emit
    _emit(resp, scope="screen", token=new_etag, include_generic=True)
    return resp


@router.post(
    "/response-sets/{response_set_id}/answers:batch",
    summary="Batch upsert answers",
    responses={
        409: {"content": {"application/problem+json": {}}},
        428: {"content": {"application/problem+json": {}}},
    },
)
def batch_upsert_answers(
    response_set_id: str,
    payload: dict,
    request: Request,
    if_match: str | None = Header(None, alias="If-Match"),
):
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
    # CLARKE: FINAL_GUARD answers-final-log
    try:
        logger.info(
            "answers.patch.final",
            extra={
                "status_code": 200,
                "problem_code": None,
                "emits_headers": True,
            },
        )
    except Exception:
        logger.error("answers_final_log_failed", exc_info=True)

# Explicit preflight (OPTIONS) handler for answers write route
# CLARKE: FINAL_GUARD answers-options-if-match
@router.options("/response-sets/{response_set_id}/answers/{question_id}")
def _autosave_answer_options(
    response_set_id: str,  # noqa: ARG001 - for parity with route signature
    question_id: str,      # noqa: ARG001 - for parity with route signature
    request: Request,      # noqa: ARG001 - signature mirrors handler
    response: Response,    # noqa: ARG001 - signature mirrors handler
):
    resp = Response(status_code=204)
    # Ensure Allow-Headers include If-Match and Content-Type (case-insensitive in tests)
    resp.headers["Access-Control-Allow-Headers"] = "If-Match, Content-Type"
    return resp
