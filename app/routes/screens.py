"""Screen view and gating endpoints.

Implements:
- GET /response-sets/{response_set_id}/screens/{screen_id}
  - Returns screen metadata and bound questions for the screen
  - Emits an ETag header derived from latest answer state for the screen
- POST /response-sets/{id}/regenerate-check
  - Delegates to gating logic
"""

from __future__ import annotations

 

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
import logging

from app.logic.etag import compute_screen_etag
from app.logic.repository_screens import (
    count_responses_for_screen,
    get_screen_metadata,
    list_questions_for_screen,
)

from app.logic.gating import evaluate_gating


router = APIRouter()
logger = logging.getLogger(__name__)




@router.get(
    "/response-sets/{response_set_id}/screens/{screen_id}",
    summary="Get a screen with its questions and any existing answers",
    operation_id="getScreenWithAnswers",
    tags=["ScreenView"],
)
def get_screen(response_set_id: str, screen_id: str, response: Response):
    # Resolve screen metadata
    meta = get_screen_metadata(screen_id)
    if not meta:
        # Unknown screen id -> 404 Problem (problem+json)
        return JSONResponse(
            {"title": "Screen not found", "status": 404},
            status_code=404,
            media_type="application/problem+json",
        )
    screen_key, title = meta[0], meta[1]
    # Diagnostic: compute count of existing responses for this screen before any handler logic
    before_count = None
    try:
        before_count = count_responses_for_screen(response_set_id, screen_key)
    except SQLAlchemyError:
        logger.error(
            "screen_precheck_count_failed rs_id=%s screen_key=%s",
            response_set_id,
            screen_key,
            exc_info=True,
        )
        before_count = -1
    # Load questions bound to the screen
    questions = list_questions_for_screen(screen_key)
    # Emit ETag and log for correlation with subsequent If-Match checks
    etag = compute_screen_etag(response_set_id, screen_key)
    response.headers["ETag"] = etag
    # Diagnostic: compute count again after handler query work; GET must be read-only
    after_count = before_count
    try:
        after_count = count_responses_for_screen(response_set_id, screen_key)
    except SQLAlchemyError:
        logger.error(
            "screen_postcheck_count_failed rs_id=%s screen_key=%s",
            response_set_id,
            screen_key,
            exc_info=True,
        )
        after_count = -1
    logger.info(
        "screen_get response_set_id=%s screen_id=%s screen_key=%s etag=%s before_count=%s after_count=%s",
        response_set_id,
        screen_id,
        screen_key,
        etag,
        before_count,
        after_count,
    )
    # Return nested object per feature/spec
    return {
        "screen": {
            "screen_id": screen_id,
            "screen_key": screen_key,
            "title": title,
        },
        "questions": questions,
    }


@router.post(
    "/response-sets/{id}/regenerate-check",
    summary="Check whether generation may proceed (gating)",
    operation_id="regenerateCheck",
    tags=["Gating"],
)
def regenerate_check(id: str):
    return evaluate_gating({"response_set_id": id})
