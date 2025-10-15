"""Authoring skeleton routes (Epic G) — 501 Problem+JSON placeholders.

Defines minimal POST endpoints for authoring operations to satisfy
integration tests until full implementation exists. No business logic.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse


# NOTE: The parent application mounts this router under '/api/v1'.
# Therefore this router should use '/authoring' so the final path resolves to
# '/api/v1/authoring/...', matching the specification and integration tests.
router = APIRouter(prefix="/authoring")


def _problem_not_implemented(detail: str) -> JSONResponse:
    body = {
        "type": "about:blank",
        "title": "Not Implemented",
        "status": 501,
        "detail": detail,
        "code": "not_implemented",
    }
    return JSONResponse(content=body, status_code=501, media_type="application/problem+json")


@router.post("/questionnaires/{questionnaire_id}/screens")
async def create_screen(
    questionnaire_id: str,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    # Skeleton only — return Problem+JSON 501 until implemented
    return _problem_not_implemented("Authoring screen creation not yet implemented")


@router.post("/questionnaires/{questionnaire_id}/questions")
async def create_question(
    questionnaire_id: str,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    # Skeleton only — return Problem+JSON 501 until implemented
    return _problem_not_implemented("Authoring question creation not yet implemented")


__all__ = ["router", "create_screen", "create_question"]


# --- Skeleton PATCH handlers requested by Clarke (no business logic) ---


@router.patch("/questionnaires/{questionnaire_id}/screens/{screen_id}")
async def update_screen(
    questionnaire_id: str,
    screen_id: str,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
) -> JSONResponse:
    return _problem_not_implemented("Authoring screen update not yet implemented")


@router.patch("/questions/{question_id}/position")
async def update_question_position(
    question_id: str,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
) -> JSONResponse:
    return _problem_not_implemented("Authoring question position update not yet implemented")


@router.patch("/questions/{question_id}")
async def update_question(
    question_id: str,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
) -> JSONResponse:
    """Skeleton for updating question text.

    Returns RFC7807 Problem+JSON with 501 until implemented.
    """
    return _problem_not_implemented("Authoring question update not yet implemented")


@router.patch("/questions/{question_id}/visibility")
async def update_question_visibility(
    question_id: str,
    if_match: Optional[str] = Header(default=None, alias="If-Match"),
) -> JSONResponse:
    """Skeleton for updating question visibility (parent/visible_if_value).

    Returns RFC7807 Problem+JSON with 501 until implemented.
    """
    return _problem_not_implemented("Authoring question visibility update not yet implemented")
