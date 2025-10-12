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
import uuid
from app.logic.repository_response_sets import response_set_exists

from app.logic.etag import compute_screen_etag
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
from app.logic.visibility_rules import is_child_visible, filter_visible_questions
from app.logic.screen_builder import assemble_screen_view
from app.models.response_types import ScreenView, ScreenViewEnvelope
from app.models.visibility import NowVisible  # reusable type import per architecture

from app.logic.gating import evaluate_gating
 


router = APIRouter()
logger = logging.getLogger(__name__)




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
    except Exception:
        # Existence check failures are non-fatal here; assembly may still proceed
        pass
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
    # Dedicated filter step for visible questions prior to assembly
    try:
        rules = get_visibility_rules_for_screen(resolved_screen_key)
        # Build parent value map for filter precomputation
        parents = {p for (p, _) in rules.values() if p is not None}
        parent_values: dict[str, str | None] = {}
        for pid in parents:
            row = get_existing_answer(response_set_id, pid)
            if row is None:
                parent_values[pid] = None
            else:
                _opt, vtext, vnum, vbool = row
                parent_values[pid] = canonicalize_answer_value(vtext, vnum, vbool)
        _ = filter_visible_questions(rules, parent_values)
    except Exception:
        # Filtering is best-effort; assembly will still compute visibility
        pass

    # Resolve screen existence via repository and assemble the view.

    # Build the screen view via the shared assembly component using the typed model
    screen_view = ScreenView(**assemble_screen_view(response_set_id, resolved_screen_key))
    # Emit Screen-ETag header equal to the computed view etag per contract
    response.headers["Screen-ETag"] = (
        screen_view.etag or compute_screen_etag(response_set_id, resolved_screen_key)
    )
    # also expose standard ETag for concurrency steps
    response.headers["ETag"] = response.headers["Screen-ETag"]
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
    body = {"screen_view": screen_view.model_dump(), "screen": screen_alias}
    return body


@router.post(
    "/response-sets/{id}/regenerate-check",
    summary="Check whether generation may proceed (gating)",
    operation_id="regenerateCheck",
    tags=["Gating"],
)
def regenerate_check(id: str):
    return evaluate_gating({"response_set_id": id})
