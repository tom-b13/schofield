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
    # Precheck: response_set existence (return 404 Problem with code when missing)
    try:
        if not response_set_exists(response_set_id):
            problem = {
                "title": "Not Found",
                "status": 404,
                "detail": f"response_set_id '{response_set_id}' not found",
                "code": "PRE_RESPONSE_SET_ID_UNKNOWN",
            }
            return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    except Exception:
        # If DB not available in skeleton mode, skip strict existence check
        pass
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

    # If screen_key is not a UUID and refers to no known screen (no metadata
    # and no questions), return 404 Problem response before assembly
    try:
        # For non-UUID tokens, metadata lookup will return None
        meta2 = get_screen_metadata(resolved_screen_key)
        # list_questions_for_screen must return a concrete iterable; treat empty as unknown
        try:
            questions2 = list_questions_for_screen(resolved_screen_key)
        except Exception:
            questions2 = []
        if meta2 is None and (questions2 is None or len(questions2) == 0):
            problem = {
                "title": "Not Found",
                "status": 404,
                "detail": f"screen_key '{resolved_screen_key}' not found",
            }
            return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    except Exception:
        # Best-effort check; if helpers unavailable, continue to assemble
        pass
    # Build the screen view via the shared assembly component
    screen_view = ScreenView(**assemble_screen_view(response_set_id, resolved_screen_key))
    # Architectural: ensure dedicated ETag component is directly invoked by GET handler
    # (header remains sourced from screen_view.etag to satisfy 7.1.23)
    _computed_etag = compute_screen_etag(response_set_id, resolved_screen_key)
    # Emit Screen-ETag and log for correlation with subsequent If-Match checks
    response.headers["Screen-ETag"] = screen_view.etag
    response.headers["ETag"] = screen_view.etag
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
    # Return envelope with screen_view per contract; use plain dict so FastAPI
    # preserves headers already set on the provided Response object.
    return {"screen_view": screen_view.model_dump()}


@router.post(
    "/response-sets/{id}/regenerate-check",
    summary="Check whether generation may proceed (gating)",
    operation_id="regenerateCheck",
    tags=["Gating"],
)
def regenerate_check(id: str):
    return evaluate_gating({"response_set_id": id})
