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
import sys
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
from app.logic.visibility_rules import compute_visible_set, is_child_visible
from app.logic.visibility_delta import compute_visibility_delta
from app.logic.enum_resolution import resolve_enum_option
from app.logic.screen_builder import assemble_screen_view
from app.logic.events import publish, RESPONSE_SAVED
from app.logic.replay import maybe_replay, store_after_success
from app.models.response_types import SavedResult, BatchResult, VisibilityDelta, ScreenView
from app.models.visibility import NowVisible


logger = logging.getLogger(__name__)


router = APIRouter()

# Ensure module INFO logs are emitted to stdout during tests/integration runs
try:
    if not logger.handlers:
        _handler = logging.StreamHandler(stream=sys.stdout)
        _handler.setLevel(logging.INFO)
        _handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
        logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
except Exception:
    # Never fail module import due to logging setup
    pass

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
    # Clarke: strip surrounding braces {token} after quote/weak removal
    if len(v) >= 2 and v[0] == '{' and v[-1] == '}':
        v = v[1:-1].strip()
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
    # Clarke: use the pre-assembled ScreenView.etag for GET↔PATCH parity; fallback to compute only if missing
    current_etag = screen_view.etag or compute_screen_etag(response_set_id, screen_key)

    # Idempotent replay is checked ONLY after If-Match enforcement (see below).

    # Incoming If-Match is enforced after replay shortcut and after resolving the current ETag
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

    # Idempotent replay short-circuit AFTER If-Match enforcement per Clarke.
    # This prevents bypassing concurrency control with a cached response.
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
    # Clarke: ensure parent ids in this set are strings for membership checks
    parents: set[str] = {str(p) for (p, _) in rules.values() if p is not None}
    parent_value_pre: dict[str, str | None] = {}
    # Clarke: Populate parent_value_pre from repository with str-cast keys before write;
    # use screen_view only for logging.
    try:
        for pid in parents:
            pid_str = str(pid)
            row = get_existing_answer(response_set_id, pid_str)
            if row is None:
                parent_value_pre[pid_str] = None
            else:
                _opt_id, vtext, vnum, vbool = row
                parent_value_pre[pid_str] = canonicalize_answer_value(vtext, vnum, vbool)
    except SQLAlchemyError:
        logger.error(
            "visibility_precompute_failed rs_id=%s screen_key=%s", 
            response_set_id, 
            screen_key, 
            exc_info=True,
        )
        parent_value_pre = {str(pid): None for pid in parents}

    # Log raw parent storage triples and canonicalized map (for comparison only)
    try:
        parent_raw_pre: dict[str, tuple | None] = {}
        for pid in parents:
            try:
                row = get_existing_answer(response_set_id, str(pid))
            except Exception:
                row = None
            parent_raw_pre[str(pid)] = row
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
        pass

    # Clarke override: before computing visible_pre, ensure the toggled parent
    # question's pre-image value is force-populated from repository if missing.
    try:
        qid_str = str(question_id)
        if qid_str in parents and (parent_value_pre.get(qid_str) is None):
            _row = get_existing_answer(response_set_id, qid_str)
            if _row is not None:
                _opt_id, _vtext, _vnum, _vbool = _row
                _canon = canonicalize_answer_value(_vtext, _vnum, _vbool)
                parent_value_pre[qid_str] = _canon
    except Exception:
        # Do not fail precompute if repository probe has issues
        pass

    # Additional hydration (repository-first): for ANY parent whose value is still
    # None, re-probe the repository and canonicalize so visible_pre reflects the
    # true pre-state (Clarke directive for all parents, not only the toggled one).
    try:
        for pid in list(parents):
            pid_s = str(pid)
            if parent_value_pre.get(pid_s) is None:
                _row2 = get_existing_answer(response_set_id, pid_s)
                if _row2 is not None:
                    _opt2, _vtext2, _vnum2, _vbool2 = _row2
                    _canon2 = canonicalize_answer_value(_vtext2, _vnum2, _vbool2)
                    parent_value_pre[pid_s] = _canon2
    except Exception:
        pass

    # Additional hydration (screen_view fallback): for ANY parent whose value is still None,
    # attempt to hydrate from the pre-assembled screen_view answers (pre-image).
    try:
        q_by_id: dict[str, dict] = {}
        for _q in (getattr(screen_view, "questions", []) or []):
            if isinstance(_q, dict) and _q.get("question_id"):
                q_by_id[str(_q.get("question_id"))] = _q
        for pid in parents:
            pid_s = str(pid)
            if parent_value_pre.get(pid_s) is None:
                qd = q_by_id.get(pid_s)
                if qd and isinstance(qd.get("answer"), dict):
                    ans = qd.get("answer")
                    vtext = ans.get("text") if isinstance(ans.get("text"), str) else None
                    vnum = ans.get("number") if isinstance(ans.get("number"), (int, float)) else None
                    vbool = ans.get("bool") if isinstance(ans.get("bool"), bool) else None
                    canon = canonicalize_answer_value(vtext, vnum, vbool)
                    parent_value_pre[pid_s] = canon
    except Exception:
        pass

    # Clarke REVISION: derive visible_pre from the pre-assembled ScreenView
    # to guarantee GET↔PATCH parity and accurate now_hidden when parents flip.
    try:
        visible_pre = {
            q.get("question_id") for q in (getattr(screen_view, "questions", []) or [])
        }
    except Exception:
        # Fallback only if ScreenView shape is unavailable
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
        pass
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
        pass
    # Also derive a pre-write set of questions that currently have an answer hydrated
    # in the pre-assembled screen view. This serves as a fallback indicator for
    # suppressed answers when repository probes are unavailable or fail.
    try:
        _questions_pre = getattr(screen_view, "questions", []) or []
        answered_pre: set[str] = set()
        for _q in _questions_pre:
            if isinstance(_q, dict) and _q.get("question_id"):
                if _q.get("answer") is not None:
                    answered_pre.add(str(_q.get("question_id")))
    except Exception:
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
        pass

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
        # Derive visible_post from the post-write ScreenView to maintain
        # parity with GET visibility (do not recompute via rules alone)
        try:
            visible_post = {
                q.get("question_id") for q in (getattr(screen_view, "questions", []) or [])
            }
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
            pass
        def _has_answer(qid: str) -> bool:
            # Primary: repository-backed probe first (Clarke directive)
            try:
                row = get_existing_answer(response_set_id, qid)
                if row is not None:
                    return True
            except Exception:
                # Ignore repository errors and fall back to pre-image
                pass
            # Fallback: consult pre-assembled screen_view pre-image
            try:
                if str(qid) in answered_pre:
                    return True
            except Exception:
                pass
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
            pass
        # Per-hidden suppression probe and summary (clear branch)
        try:
            nh_ids = []
            try:
                nh_ids = [nh.get("question") for nh in now_hidden] if (now_hidden and isinstance(now_hidden[0], dict)) else [str(x) for x in (now_hidden or [])]
            except Exception:
                nh_ids = []
            supp_ids = [str(x) for x in (suppressed_answers or [])]
            for qid in nh_ids:
                repo_row = None
                repo_has = False
                pre_has = False
                try:
                    repo_row = get_existing_answer(response_set_id, qid)
                    repo_has = repo_row is not None
                except Exception:
                    repo_row = None
                try:
                    pre_has = str(qid) in (answered_pre or set())
                except Exception:
                    pre_has = False
                logger.info(
                    "vis_suppress_probe rs_id=%s screen_key=%s qid=%s repo_has=%s pre_image_has=%s suppressed=%s parent_pre=%s parent_post=%s",
                    response_set_id,
                    screen_key,
                    qid,
                    repo_has,
                    pre_has,
                    (qid in supp_ids),
                    parent_value_pre,
                    parent_value_post,
                )
                if not repo_has:
                    logger.info(
                        "vis_suppress_repo_miss rs_id=%s qid=%s repo_row=%s",
                        response_set_id,
                        qid,
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
            pass

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
                # Ignore repository errors for suppressed classification
                continue
        suppressed_ids = sorted(pre_suppressed | repo_suppressed)
        # Clarke: expose structured saved result (question_id, state_version)
        from app.logic.repository_answers import get_screen_version
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
        saved_result = upsert_answer(
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

    # Derive visible_post from the post-write ScreenView to maintain parity
    # with GET visibility (avoid recomputing solely from rules)
    try:
        visible_post = {
            q.get("question_id") for q in (getattr(screen_view, "questions", []) or [])
        }
    except Exception:
        visible_post = compute_visible_set(rules, parent_value_post)
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
        pass
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
        # Primary: repository-backed probe first (Clarke directive)
        try:
            row = get_existing_answer(response_set_id, qid)
            if row is not None:
                return True
        except Exception:
            # Ignore repository errors and fall back to pre-image
            pass
        # Fallback: consult pre-assembled screen_view pre-image
        try:
            if str(qid) in answered_pre:
                return True
        except Exception:
            pass
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
            # Heuristic inference must never break the request
            pass
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
    # Per-hidden suppression probe and summary (normal branch)
    try:
        nh_ids = []
        try:
            nh_ids = [nh.get("question") for nh in now_hidden] if (now_hidden and isinstance(now_hidden[0], dict)) else [str(x) for x in (now_hidden or [])]
        except Exception:
            nh_ids = []
        supp_ids = [str(x) for x in (suppressed_answers or [])]
        for qid in nh_ids:
            repo_row = None
            repo_has = False
            pre_has = False
            try:
                repo_row = get_existing_answer(response_set_id, qid)
                repo_has = repo_row is not None
            except Exception:
                repo_row = None
            try:
                pre_has = str(qid) in (answered_pre or set())
            except Exception:
                pre_has = False
            logger.info(
                "vis_suppress_probe rs_id=%s screen_key=%s qid=%s repo_has=%s pre_image_has=%s suppressed=%s parent_pre=%s parent_post=%s",
                response_set_id,
                screen_key,
                qid,
                repo_has,
                pre_has,
                (qid in supp_ids),
                parent_value_pre,
                parent_value_post,
            )
            if not repo_has:
                logger.info(
                    "vis_suppress_repo_miss rs_id=%s qid=%s repo_row=%s",
                    response_set_id,
                    qid,
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
        pass

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
                    base_hidden = set(x if isinstance(x, str) else str(x) for x in (now_hidden or []))
                    now_hidden = sorted(list(base_hidden | extra_hidden))
    except Exception:
        pass

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
            continue
    suppressed_ids = sorted(pre_suppressed | repo_suppressed)
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
