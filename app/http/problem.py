"""Problem+JSON utilities and global exception handlers (Epic K).

Defines RFC7807 media type and handler callables that produce
application/problem+json responses.
"""

from __future__ import annotations

from typing import Any
import logging
from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi import HTTPException
from fastapi.responses import JSONResponse

PROBLEM_MEDIA_TYPE = "application/problem+json"

logger = logging.getLogger(__name__)


async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:  # noqa: D401
    try:
        detail = exc.detail if isinstance(getattr(exc, "detail", None), dict) else {
            "title": "Error",
            "status": int(getattr(exc, "status_code", 500) or 500),
            "detail": str(getattr(exc, "detail", "")),
        }
    except Exception:
        detail = {"title": "Error", "status": 500}
    return JSONResponse(detail, status_code=int(getattr(exc, "status_code", 500) or 500), media_type=PROBLEM_MEDIA_TYPE)


async def handle_request_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:  # noqa: D401
    try:
        problem = {
            "title": "Invalid Request",
            "status": 422,
            "detail": "Request validation failed",
            "errors": list(getattr(exc, "errors", lambda: [])()),
        }
    except Exception:
        problem = {"title": "Invalid Request", "status": 422}
    return JSONResponse(problem, status_code=422, media_type=PROBLEM_MEDIA_TYPE)


async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:  # noqa: D401
    try:
        logger.error("unexpected_error", exc_info=True)
    except Exception:
        pass
    return JSONResponse({"title": "Internal Server Error", "status": 500}, status_code=500, media_type=PROBLEM_MEDIA_TYPE)


__all__ = [
    "PROBLEM_MEDIA_TYPE",
    "handle_http_exception",
    "handle_request_validation_error",
    "handle_unexpected_error",
]

