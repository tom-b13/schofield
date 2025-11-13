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
    # Prepare headers from the HTTPException to preserve upstream signals (e.g., ETag)
    headers: dict[str, str] = {}
    try:
        exc_headers = getattr(exc, "headers", None)
        if isinstance(exc_headers, dict):
            headers.update({str(k): str(v) for k, v in exc_headers.items()})
    except Exception:
        # If header extraction fails, fall back silently to empty headers
        headers = {}
    # Safety net for Epic K answers PATCH errors (409/428): ensure ETag and Screen-ETag are present
    try:
        status_code = int(getattr(exc, "status_code", 500) or 500)
        method = str(getattr(request, "method", ""))
        path_params = getattr(request, "path_params", {}) or {}
        is_answers_route = (
            isinstance(path_params, dict)
            and "response_set_id" in path_params
            and "question_id" in path_params
        )
        if method.upper() == "PATCH" and is_answers_route and status_code in (409, 428):
            # Only add if missing or empty; do not overwrite non-empty values
            et_present = isinstance(headers.get("ETag"), str) and headers.get("ETag").strip() != ""
            sc_present = isinstance(headers.get("Screen-ETag"), str) and headers.get("Screen-ETag").strip() != ""
            if not (et_present and sc_present):
                rsid = str(path_params.get("response_set_id"))
                qid = str(path_params.get("question_id"))
                token = ""
                # Primary: repository_screens lookup
                try:
                    from app.logic.repository_screens import get_screen_key_for_question as _screen_key_primary  # type: ignore
                    from app.logic.etag import compute_screen_etag as _compute  # type: ignore
                    skey = _screen_key_primary(qid)
                    token = _compute(rsid, skey) if skey else ""
                except Exception:
                    token = ""
                # Secondary: repository_answers fallback when primary fails or empty
                if not token:
                    try:
                        from app.logic.repository_answers import get_screen_key_for_question as _screen_key_fallback  # type: ignore
                        from app.logic.etag import compute_screen_etag as _compute2  # type: ignore
                        skey2 = _screen_key_fallback(qid)
                        token = _compute2(rsid, skey2) if skey2 else ""
                    except Exception:
                        token = token or ""
                # Tertiary: derive from request body then stable surrogate (question_id)
                if not token:
                    try:
                        import json as _json
                        raw = getattr(request, "_body", None)
                        parsed = None
                        if isinstance(raw, (bytes, bytearray)) and raw:
                            try:
                                parsed = _json.loads(raw.decode("utf-8", errors="ignore"))
                            except Exception:
                                parsed = None
                        elif isinstance(raw, dict):
                            parsed = raw
                        skey3 = None
                        if isinstance(parsed, dict):
                            v = parsed.get("screen_key")
                            if isinstance(v, str) and v:
                                skey3 = v
                        if not skey3:
                            skey3 = qid
                        if skey3:
                            from app.logic.etag import compute_screen_etag as _compute3  # type: ignore
                            token = _compute3(rsid, skey3) or ""
                    except Exception:
                        token = token or ""
                # Set only missing/empty values
                if not et_present and token:
                    headers["ETag"] = token
                if not sc_present and token:
                    headers["Screen-ETag"] = token
                # Expose via CORS, ensuring each appears once
                try:
                    aceh = headers.get("Access-Control-Expose-Headers", "")
                    needed = ["ETag", "Screen-ETag"]
                    current = [h.strip() for h in aceh.split(",") if h.strip()] if aceh else []
                    for name in needed:
                        if name not in current:
                            current.append(name)
                    if current:
                        headers["Access-Control-Expose-Headers"] = ", ".join(current)
                except Exception:
                    # Non-critical; continue
                    pass
    except Exception:
        # Do not let safety net affect handler behaviour
        pass
    return JSONResponse(
        detail,
        status_code=int(getattr(exc, "status_code", 500) or 500),
        media_type=PROBLEM_MEDIA_TYPE,
        headers=headers or None,
    )


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
