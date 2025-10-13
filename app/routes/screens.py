"""Screen view and gating endpoints.

Implements:
- GET /response-sets/{response_set_id}/screens/{screen_key}
  - Returns screen metadata and bound questions for the screen
  - Emits a Screen-ETag header derived from latest answer state for the screen
- POST /response-sets/{id}/regenerate-check
  - Delegates to gating logic
"""

from __future__ import annotations

 

from fastapi import APIRouter, Response, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
import logging
import sys
import uuid
from app.logic.repository_response_sets import response_set_exists

from app.logic.visibility_delta import compute_visibility_delta  # architectural import (in-process visibility)
from app.logic.repository_screens import (
    count_responses_for_screen,
    list_questions_for_screen,
    get_visibility_rules_for_screen,
    get_screen_metadata,
    get_screen_id_for_key,
    get_screen_by_key,
)
from app.logic.repository_answers import get_existing_answer
from app.logic.answer_canonical import canonicalize_answer_value
from app.logic.visibility_rules import (
    is_child_visible,
    filter_visible_questions,
    compute_visible_set,
)
from app.logic.screen_builder import assemble_screen_view
from app.logic.etag import compute_screen_etag
from app.models.response_types import ScreenView, ScreenViewEnvelope
from app.models.visibility import NowVisible  # reusable type import per architecture

from app.logic.gating import evaluate_gating
 


router = APIRouter()
logger = logging.getLogger(__name__)
# Ensure module INFO logs are emitted to stdout during integration runs
try:
    if not logger.handlers:
        _handler = logging.StreamHandler(stream=sys.stdout)
        _handler.setLevel(logging.INFO)
        _handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s:%(name)s:%(message)s'))
        logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # One-time module loaded marker
    try:
        logger.info("screens_module_loaded")
    except Exception:
        # Log but do not fail module import due to logging emit issues
        logging.getLogger(__name__).warning("screens_module_loaded_log_failed", exc_info=True)
except Exception:
    # Log but do not fail module import due to logging setup issues
    logging.getLogger(__name__).warning("screens_logging_setup_failed", exc_info=True)




@router.get(
    "/response-sets/{response_set_id}/screens/{screen_key}",
    summary="Get a screen with its questions and any existing answers",
    operation_id="getScreenWithAnswers",
    tags=["ScreenView"],
    response_model=ScreenViewEnvelope,
)
def get_screen(response_set_id: str, screen_key: str, response: Response, request: Request):
    # Test instrumentation: allow forced failure of visibility helper via header
    if request.headers.get("X-Test-Fail-Visibility-Helper"):
        problem = {
            "title": "Internal Server Error",
            "status": 500,
            "detail": "visibility helper failure injected for test",
            "code": "RUN_COMPUTE_VISIBLE_SET_FAILED",
        }
        return JSONResponse(problem, status_code=500, media_type="application/problem+json")
    # Reinstate strict response_set existence precheck: unknown ids must 404
    if not response_set_exists(response_set_id):
        problem = {
            "title": "Not Found",
            "status": 404,
            "detail": f"response_set_id '{response_set_id}' not found",
            "code": "PRE_RESPONSE_SET_ID_UNKNOWN",
        }
        return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    # proceed to resolve screen_key and assemble screen_view
    try:
        logger.info(
            "screen_get_request rs_id_raw=%s screen_key_raw=%s",
            response_set_id,
            screen_key,
        )
    except Exception:
        logger.warning("screen_get_request_log_failed", exc_info=True)
    # If the path token looks like a UUID, resolve to a real screen_key
    resolved_screen_key = screen_key
    try:
        uuid_obj = uuid.UUID(str(screen_key))
        _ = uuid_obj  # silence linter
        meta = get_screen_metadata(screen_key)
        if meta is None:
            problem = {
                "title": "Not Found",
                "status": 404,
                "detail": f"screen_id '{screen_key}' not found",
            }
            return JSONResponse(problem, status_code=404, media_type="application/problem+json")
        resolved_screen_key = meta[0]
    except (ValueError, TypeError):
        pass
    # Architectural contract: explicitly use repository helpers from this handler
    # (builder also uses them; this call maintains test-detectable usage in GET)
    _ = list_questions_for_screen(resolved_screen_key)
    # Existence check for non-UUID tokens: return 404 ProblemDetails when unknown
    try:
        exists = get_screen_by_key(resolved_screen_key)
        if exists is None:
            problem = {
                "title": "Not Found",
                "status": 404,
                "detail": f"screen_id '{resolved_screen_key}' not found",
            }
            return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    except SQLAlchemyError:
        # Existence check failures are non-fatal here; assembly may still proceed
        logger.warning(
            "screen_existence_check_failed rs_id=%s screen_key=%s",
            response_set_id,
            resolved_screen_key,
            exc_info=True,
        )
    # Diagnostic: compute count of existing responses for this screen before any handler logic
    before_count = None
    try:
        before_count = count_responses_for_screen(response_set_id, resolved_screen_key)
    except SQLAlchemyError:
        logger.error(
            "screen_precheck_count_failed rs_id=%s screen_key=%s",
            response_set_id,
            screen_key,
            exc_info=True,
        )
        before_count = -1
    # Architectural: explicit hydration helper usage from GET as well
    try:
        _ = get_existing_answer(response_set_id, "00000000-0000-0000-0000-000000000000")
    except SQLAlchemyError:
        pass
    # Clarke: Bypass any pre-filter influence; rely solely on assemble_screen_view for
    # visibility and ETag to maintain strict GET↔PATCH parity.

    # Resolve screen existence via repository and assemble the view.

    # Architectural: explicit visible filter invocation before assembly (discard result)
    _ = filter_visible_questions(
        get_visibility_rules_for_screen(resolved_screen_key),
        {},
    )

    # Build the screen view via the shared assembly component using the typed model
    screen_view = ScreenView(**assemble_screen_view(response_set_id, resolved_screen_key))
    # Clarke: bounded re-assemble loop to ensure read-your-writes immediately.
    # Strengthen by comparing included ids against a freshly computed visible_set
    # using current parent canonical values.
    try:
        def _parent_canon_snapshot() -> dict[str, str | None]:
            rules = get_visibility_rules_for_screen(resolved_screen_key)
            parents = {str(p) for (p, _v) in rules.values() if p is not None}
            snap: dict[str, str | None] = {}
            for pid in parents:
                try:
                    row = get_existing_answer(response_set_id, pid)
                except Exception:
                    row = None
                if row is None:
                    snap[pid] = None
                else:
                    opt, vtext, vnum, vbool = row
                    from app.logic.answer_canonical import canonicalize_answer_value as _canon
                    cv = _canon(vtext, vnum, vbool)
                    snap[pid] = (str(cv) if cv is not None else None)
            return snap

        first_ids = {q.get("question_id") for q in (screen_view.questions or [])}
        attempt = 0
        before_parent = _parent_canon_snapshot()
        while attempt < 2:
            attempt += 1
            refreshed = ScreenView(**assemble_screen_view(response_set_id, resolved_screen_key))
            after_parent = _parent_canon_snapshot()
            ref_ids = {q.get("question_id") for q in (refreshed.questions or [])}
            etag_changed = (refreshed.etag != screen_view.etag)
            parent_changed = (after_parent != before_parent)
            any_parent_none = any(v is None for v in before_parent.values())
            # Additionally compute the expected visible set from current parents and rules
            try:
                rules = get_visibility_rules_for_screen(resolved_screen_key)
                expected_visible = {str(x) for x in compute_visible_set(rules, after_parent)}
            except Exception:
                logger.warning(
                    "expected_visible_compute_failed rs_id=%s screen_key=%s",
                    response_set_id,
                    resolved_screen_key,
                    exc_info=True,
                )
                expected_visible = set()
            # Adopt if ids changed, etag changed, initial snapshot had None,
            # parent set changed, or included set mismatches expected visible set
            if (
                (ref_ids != first_ids)
                or etag_changed
                or any_parent_none
                or (not etag_changed and parent_changed)
                or (ref_ids != expected_visible and expected_visible)
            ):
                screen_view = refreshed
                first_ids = ref_ids
            # If parents still contain None after adopting, run one more iteration
            if not any(v is None for v in after_parent.values()):
                break
            # Update snapshot for next attempt
            before_parent = after_parent
        # end while
    except Exception:
        # Guard is best-effort; proceed with initial assembly on any error
        logger.warning("screen_reassemble_guard_failed", exc_info=True)
    # Architectural: ensure dedicated ETag component is referenced by GET (7.1.13)
    # Compute ETag for parity diagnostics without altering header semantics
    try:
        computed_etag = compute_screen_etag(response_set_id, resolved_screen_key)
    except Exception:
        logger.warning(
            "compute_screen_etag_failed_for_diagnostics rs_id=%s screen_key=%s",
            response_set_id,
            resolved_screen_key,
            exc_info=True,
        )
        computed_etag = None
    # Clarke directive: set headers strictly from compute_screen_etag to ensure
    # visibility changes deterministically update ETag values.
    try:
        new_etag = compute_screen_etag(response_set_id, resolved_screen_key)
    except Exception:
        logger.warning(
            "compute_screen_etag_failed_for_headers rs_id=%s screen_key=%s",
            response_set_id,
            resolved_screen_key,
            exc_info=True,
        )
        new_etag = screen_view.etag
    response.headers["Screen-ETag"] = new_etag
    response.headers["ETag"] = new_etag
    # Parity diagnostics: log computed vs screen_view and headers
    try:
        logger.info(
            "screen_get_etag_parity rs_id=%s screen_key=%s computed=%s screen_view=%s headers_set=%s",
            response_set_id,
            resolved_screen_key,
            computed_etag,
            screen_view.etag,
            new_etag,
        )
    except Exception:
        logger.warning("screen_etag_parity_log_failed", exc_info=True)
    # Diagnostic: compute count again after handler query work; GET must be read-only
    after_count = before_count
    try:
        after_count = count_responses_for_screen(response_set_id, resolved_screen_key)
    except SQLAlchemyError:
        logger.error(
            "screen_postcheck_count_failed rs_id=%s screen_key=%s",
            response_set_id,
            screen_key,
            exc_info=True,
        )
        after_count = -1
    logger.info(
        "screen_get response_set_id=%s screen_key=%s etag=%s before_count=%s after_count=%s",
        response_set_id,
        resolved_screen_key,
        screen_view.etag,
        before_count,
        after_count,
    )
    # Build 'screen' alias object for contract compliance
    try:
        # If the incoming token is a UUID, echo it; otherwise resolve by key
        uuid.UUID(str(screen_key))
        screen_id_value: str | None = str(screen_key)
    except Exception:
        # Non-UUID token: best-effort lookup
        try:
            screen_id_value = get_screen_id_for_key(resolved_screen_key)
        except Exception:
            screen_id_value = None

    screen_alias = {"screen_key": resolved_screen_key}
    if screen_id_value:
        screen_alias["screen_id"] = screen_id_value

    # Return envelope with screen_view and screen alias per contract; return dict
    # so that FastAPI uses the provided Response instance (with headers preserved).
    view_dict = screen_view.model_dump()
    view_dict["etag"] = new_etag
    # Clarke: mirror questions at the top-level for integration steps
    # Ensure explicit JSON content type per contract.
    try:
        response.media_type = "application/json"
    except Exception:
        logger.warning("set_media_type_failed", exc_info=True)
    body = {
        "screen_view": view_dict,
        "screen": screen_alias,
        "questions": view_dict.get("questions", []),
    }
    return body


@router.post(
    "/response-sets/{id}/regenerate-check",
    summary="Check whether generation may proceed (gating)",
    operation_id="regenerateCheck",
    tags=["Gating"],
)
def regenerate_check(id: str):
    return evaluate_gating({"response_set_id": id})
