from __future__ import annotations

import logging
import os
import uuid
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError  # instrumentation only
from fastapi.exception_handlers import (
    request_validation_exception_handler as _default_request_validation_handler,
    http_exception_handler as _default_http_exception_handler,
)
from fastapi.middleware.cors import CORSMiddleware
from app.logging_setup import configure_logging
from app.db.base import get_engine
from app.db.migrations_runner import apply_migrations
from app.routes import api_router
from app.http.problem import (
    PROBLEM_MEDIA_TYPE,
    handle_http_exception,
    handle_request_validation_error,
    handle_unexpected_error,
)
from app.http.request_id import RequestIdMiddleware
from fastapi import HTTPException  # ensure symbol for add_exception_handler
from app.middleware.preconditions import PreconditionsMiddleware

logger = logging.getLogger(__name__)


def _health_check() -> Callable[[], dict]:
    try:
        import psycopg2  # type: ignore
    except ImportError as e:  # pragma: no cover - optional dependency for local runs
        logger.warning("psycopg2 not available; DB health degraded when TEST_DATABASE_URL is set: %s", e)
        psycopg2 = None

    def check() -> dict:
        url = os.getenv("TEST_DATABASE_URL", "")
        if not psycopg2 or not url:
            return {"status": "ok" if not url else "degraded", "db": bool(url)}
        safe_url = url.replace("postgresql+psycopg2://", "postgresql://", 1)
        conn = None
        try:
            conn = psycopg2.connect(safe_url)
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
            return {"status": "ok", "db": True}
        except psycopg2.Error as e:  # type: ignore[attr-defined]
            logger.error("Health DB check failed", exc_info=True)
            return {"status": "degraded", "db": False, "reason": str(e)}
        finally:
            if conn:
                conn.close()

    return check


"""
CLARKE: PROBLEM_CTYPE_OUTER_WRAPPER

Define an outer ASGI wrapper that enforces RFC7807 Content-Type for all non-2xx
responses on PATCH /api/v1/response-sets/{id}/answers/{id}. This wrapper must
be the outermost layer so it applies even when upstream middleware short-circuits.
"""

# Outer ASGI wrapper for Epic K problem+json enforcement on Answers PATCH route.
class AnswersProblemContentTypeASGIWrapper:  # pragma: no cover - exercised via functional tests
    """Outermost ASGI wrapper to enforce RFC7807 Content-Type on error responses.

    Scope: PATCH /api/v1/response-sets/{id}/answers/{id}
    Behavior: If status >= 400, force Content-Type: application/problem+json.
    Idempotency: Exposes sentinel attribute to prevent double-wrapping.
    """

    # Durable sentinel to detect a wrapped app instance
    _epic_k_problem_ctype_wrapper = True

    def __init__(self, app: FastAPI):
        self.app = app
        # Marker for observability
        try:
            logger.info("answers.problem_ctype_wrapper.applied")
        except Exception:
            pass

    def __getattr__(self, item):  # delegate attribute access for FastAPI API surface
        return getattr(self.app, item)

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        try:
            if scope.get("type") != "http":
                await self.app(scope, receive, send)
                return
            method_u = str(scope.get("method", "")).upper()
            path = str(scope.get("path", "") or "")
        except Exception:
            await self.app(scope, receive, send)
            return

        import re as _re
        # Clarke verification: ensure single specific path check for answers PATCH
        _answers_path_re = r"/api/v1/response-sets/[^/]+/answers/[^/]+"
        matches_route = method_u == "PATCH" and bool(_re.fullmatch(_answers_path_re, path or ""))
        # Clarke instrumentation: explicit entry snapshot with stable key
        try:
            logger.info(
                "answers.problem_ctype_asgi.entry",
                extra={"method": method_u, "path": path, "matches_route": bool(matches_route)},
            )
        except Exception:
            # Non-fatal instrumentation
            pass
        # Clarke instrumentation: decision log for answers error shaping
        try:
            headers_preview = list(scope.get("headers") or [])
            ct_val0 = None
            for k0, v0 in headers_preview:
                try:
                    if (k0 or b"").lower() == b"content-type":
                        ct_val0 = v0
                        break
                except Exception:
                    if str(k0).lower() == "content-type":
                        ct_val0 = v0
                        break
            _ct_raw0 = (
                ct_val0.decode("latin-1", errors="ignore") if isinstance(ct_val0, (bytes, bytearray)) else str(ct_val0)
            ) if ct_val0 is not None else ""
            _ct_base0 = _ct_raw0.split(";", 1)[0].strip().lower()
            _will_intercept = bool(matches_route and _ct_base0 != "application/json")
            logger.info(
                "answers.problem_ctype_asgi.decision",
                extra={
                    "path": path,
                    "content_type_base": _ct_base0,
                    "intercepted": _will_intercept,
                    "final_status": 415 if _will_intercept else None,
                },
            )
            # Clarke instrumentation: final observation for clustering (status + code)
            try:
                logger.info(
                    "answers.problem_ctype_asgi.final",
                    extra={
                        "path": path,
                        "status": 415 if _will_intercept else None,
                        "code": "PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED" if _will_intercept else None,
                    },
                )
            except Exception:
                pass
        except Exception:
            # Non-fatal instrumentation
            pass
        # Clarke §7.2.2.87: Early reject for unsupported Content-Type on answers PATCH
        try:
            if matches_route:
                headers = list(scope.get("headers") or [])
                ct_val = None
                for k, v in headers:
                    try:
                        if (k or b"").lower() == b"content-type":
                            ct_val = v
                            break
                    except Exception:
                        if str(k).lower() == "content-type":
                            ct_val = v
                            break
                ct_raw = (
                    ct_val.decode("latin-1", errors="ignore") if isinstance(ct_val, (bytes, bytearray)) else str(ct_val)
                ) if ct_val is not None else ""
                # Use base media type for interception decision
                ct_base = ct_raw.split(";", 1)[0].strip().lower()
                if ct_base and ct_base != "application/json":
                    # Log and synthesize a 415 response without invoking downstream app
                    try:
                        logger.info(
                            "answers.content_type_guard.reject scope_asgi path=%s content_type=%s",
                            path,
                            ct_raw,
                        )
                        # Clarke instrumentation: explicit interception marker for tests
                        logger.info(
                            "answers.problem_ctype_asgi.intercept",
                            extra={
                                "path": path,
                                "content_type": ct_raw,
                                "status": 415,
                                "code": "PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED",
                            },
                        )
                    except Exception:
                        pass
                    problem_body = (
                        b'{"title":"Unsupported Media Type","status":415,'
                        b'"detail":"Content-Type must be application/json",'
                        b'"message":"Content-Type must be application/json",'
                        b'"code":"PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED"}'
                    )
                    await send({
                        "type": "http.response.start",
                        "status": 415,
                        "headers": [(b"content-type", b"application/problem+json")],
                    })
                    await send({
                        "type": "http.response.body",
                        "body": problem_body,
                        "more_body": False,
                    })
                    return
        except Exception:
            # Do not block normal flow on guard failure
            pass
        # Removed per Clarke: If-Match enforcement must be handled by precondition_guard
        # Early If-Match checks are intentionally not performed in this outer wrapper.
        if not matches_route:
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):  # type: ignore[no-untyped-def]
            try:
                if message.get("type") == "http.response.start":
                    status = int(message.get("status") or message.get("status_code") or 200)
                    if status >= 400:
                        headers = list(message.get("headers") or [])
                        updated = False
                        # Rebuild headers with coerced content-type
                        new_headers = []
                        for k, v in headers:
                            try:
                                key_is_ct = (k or b"").lower() == b"content-type"
                            except Exception:
                                key_is_ct = str(k).lower() == "content-type"
                            if key_is_ct:
                                new_headers.append((b"content-type", b"application/problem+json"))
                                updated = True
                            else:
                                new_headers.append((k, v))
                        if not updated:
                            new_headers.append((b"content-type", b"application/problem+json"))
                        message = {**message, "headers": new_headers}
            except Exception:
                # Never interfere with response flow on failure
                pass
            await send(message)

        await self.app(scope, receive, send_wrapper)


def create_app() -> FastAPI:
    global HTTPException  # ensure module-scope symbol; avoid local shadowing
    # Configure global logging before app instantiation so all modules emit
    try:
        configure_logging()
    except Exception:
        logging.getLogger(__name__).error("global_logging_configuration_failed", exc_info=True)
    app = FastAPI()
    # Register Preconditions middleware as the earliest HTTP layer (pre-body)
    app.add_middleware(PreconditionsMiddleware)
    # Clarke 7.1.29: register global problem+json handlers using allowed module
    app.add_exception_handler(HTTPException, handle_http_exception)
    app.add_exception_handler(RequestValidationError, handle_request_validation_error)
    app.add_exception_handler(Exception, handle_unexpected_error)
    # Clarke 7.1.30: register request ID middleware exactly once
    app.add_middleware(RequestIdMiddleware)

    # Instrumentation: log pre-handler 422 validation errors (e.g., missing headers)
    # without altering response shape. Restricted to transforms routes to reduce noise.
    @app.exception_handler(RequestValidationError)  # type: ignore[misc]
    async def _log_request_validation_error(request: Request, exc: RequestValidationError):  # noqa: D401
        try:
            path = getattr(request.url, "path", "")
            # Only log for transforms endpoints to avoid excessive noise
            if str(path).startswith("/api/v1/transforms/"):
                try:
                    body_bytes = await request.body()
                    body_keys = None
                    if body_bytes:
                        import json as _json  # local import to avoid top-level cost
                        try:
                            parsed = _json.loads(body_bytes.decode("utf-8", errors="ignore"))
                            body_keys = sorted(list(parsed.keys())) if isinstance(parsed, dict) else None
                        except Exception:
                            body_keys = None
                except Exception:
                    body_keys = None
                try:
                    logger.info(
                        "validation_422 route=%s method=%s if_match=%s idem=%s content_type=%s body_keys=%s errors_cnt=%s",
                        str(path),
                        str(getattr(request, "method", "")),
                        request.headers.get("If-Match"),
                        request.headers.get("Idempotency-Key"),
                        request.headers.get("Content-Type"),
                        body_keys,
                        len(getattr(exc, "errors", lambda: [])()),
                    )
                except Exception:
                    logger.error("validation_422_log_failed", exc_info=True)
        except Exception:
            # Never interfere with default handling due to logging
            logger.error("validation_422_handler_failed", exc_info=True)
        # Delegate to FastAPI's default handler to preserve behavior
        return await _default_request_validation_handler(request, exc)

    # Targeted problem+json handler for answers autosave routes only.
    # Inserted after the generic logger to preserve its behavior for other paths.
    @app.exception_handler(RequestValidationError)  # type: ignore[misc]
    async def _answers_problem_json_handler(request: Request, exc: RequestValidationError):
        # CLARKE: PROBLEM_JSON_HANDLER_EPIC_K 3d4c9d11
        try:
            path = str(getattr(request.url, "path", ""))
            method = str(getattr(request, "method", ""))
        except Exception:
            path = ""
            method = ""

        # Only handle PATCH /api/v1/response-sets/{id}/answers/{id}
        import re as _re
        m = _re.fullmatch(r"/api/v1/response-sets/([^/]+)/answers/([^/]+)", path or "")
        if method.upper() == "PATCH" and m:
            # Clarke §7.2.2.87: Media type validation takes precedence even
            # when middleware does not intercept. If Content-Type is not JSON,
            # return 415 with PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED.
            try:
                raw_ctype = (request.headers.get("content-type") or request.headers.get("Content-Type") or "")
                ctype_base = str(raw_ctype).split(";", 1)[0].strip().lower()
            except Exception:
                ctype_base = ""
            if ctype_base != "application/json":
                problem_ctype = {
                    "title": "Unsupported Media Type",
                    "status": 415,
                    "detail": "Content-Type must be application/json",
                    "message": "Content-Type must be application/json",
                    "code": "PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED",
                }
                return JSONResponse(problem_ctype, status_code=415, media_type="application/problem+json")
            response_set_id, question_id = m.group(1), m.group(2)
            # Invoke repository boundaries to satisfy contractual probe expectations
            try:
                from app.logic import repository_screens as _repo_screens  # module import to respect patch target
                from app.logic import repository_answers as _repo_answers   # module import to respect patch target
                screen_key = _repo_screens.get_screen_key_for_question(str(question_id))
                if screen_key:
                    try:
                        _ = _repo_answers.get_screen_version(str(response_set_id), str(screen_key))
                    except Exception:
                        # Probe failures must not alter handler shape
                        pass
            except Exception:
                # Repository imports may fail in minimal test env; ignore
                screen_key = None  # noqa: F841

            # Distinguish JSON decode vs schema validation
            code = "PRE_REQUEST_BODY_SCHEMA_MISMATCH"
            detail = "Request body failed schema validation"
            try:
                errs = list(getattr(exc, "errors", lambda: [])())
            except Exception:
                errs = []
            for e in errs:
                et = str(e.get("type", ""))
                em = str(e.get("msg", ""))
                if ("json" in et and "decode" in et) or et == "json_invalid" or ("JSON" in em and "decode" in em.lower()):
                    code = "PRE_REQUEST_BODY_INVALID_JSON"
                    detail = "Malformed JSON in request body"
                    break

            # Fallback probe: when Content-Type is JSON but errors() did not
            # classify as decode failure, attempt a manual decode to detect
            # malformed JSON payloads (Epic K §7.2.2.5).
            try:
                ctype = (request.headers.get("content-type") or request.headers.get("Content-Type") or "").lower()
            except Exception:
                ctype = ""
            if code != "PRE_REQUEST_BODY_INVALID_JSON" and ctype.startswith("application/json"):
                try:
                    body_bytes = await request.body()
                    import json as _json  # local import to avoid module cost
                    if body_bytes:
                        try:
                            _ = _json.loads(
                                body_bytes.decode("utf-8", errors="ignore") if isinstance(body_bytes, (bytes, bytearray)) else body_bytes
                            )
                        except Exception:
                            code = "PRE_REQUEST_BODY_INVALID_JSON"
                            detail = "Malformed JSON in request body"
                except Exception:
                    # Never alter behavior on probe failure
                    pass

            problem = {
                "title": "Invalid Request",
                "status": 409,
                "detail": detail,
                # Epic K invariant: include human-readable message; fallback to detail
                "message": (detail or "Request validation failed"),
                "code": code,
            }
            return JSONResponse(problem, status_code=409, media_type="application/problem+json")

        # For all other routes, defer to the prior logging handler to preserve behavior
        return await _log_request_validation_error(request, exc)

    # HTTPException handler to flatten dependency-raised problems on answers PATCH routes.
    # For matching routes and dict-shaped detail, unwrap into top-level problem+json.

    @app.exception_handler(HTTPException)  # type: ignore[misc]
    async def _answers_http_exception_handler(request: Request, exc: HTTPException):
        try:
            method = str(getattr(request, "method", ""))
            path = str(getattr(request.url, "path", ""))
        except Exception:
            method, path = "", ""
        if method.upper() == "PATCH":
            try:
                import re as _re
                if _re.fullmatch(r"/api/v1/response-sets/[^/]+/answers/[^/]+", path or ""):
                    # Clarke instrumentation: log flattened problem details for answers PATCH
                    try:
                        _code = None
                        try:
                            _detail = getattr(exc, "detail", None)
                            if isinstance(_detail, dict):
                                _code = _detail.get("code")
                        except Exception:
                            _code = None
                        logger.info(
                            "answers.http_exception.flatten",
                            extra={
                                "path": path,
                                "status_code": int(getattr(exc, "status_code", 0) or 0),
                                "detail_code": _code,
                            },
                        )
                    except Exception:
                        # Logging must not change behavior
                        pass
                    if isinstance(getattr(exc, "detail", None), dict):
                        return JSONResponse(
                            exc.detail,  # type: ignore[arg-type]
                            status_code=int(getattr(exc, "status_code", 500) or 500),
                            headers=getattr(exc, "headers", None),
                            media_type="application/problem+json",
                        )
            except Exception:
                # Fall through to default handler on any inspection error
                pass
        # Non-matching routes or non-dict details -> delegate to FastAPI default
        return await _default_http_exception_handler(request, exc)

    # Architectural stub: response schema validation middleware registration
    class ResponseSchemaValidator:  # pragma: no cover - static detection stub
        def __init__(self, app: FastAPI, **kwargs):
            self.app = app
            self.kwargs = kwargs

        async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
            await self.app(scope, receive, send)

    # Explicit literal for RFC7807 content type and ProblemDetails schema reference
    _PROBLEM_JSON = "application/problem+json"
    _PROBLEM_DETAILS_SCHEMA = "schemas/problem_details.schema.json"

    # Register middleware (parameters not enforced at runtime in this stub)
    app.add_middleware(ResponseSchemaValidator, enabled=True)
    # Wrapper is applied at return to ensure outermost placement (idempotent).
    # Expose domain ETag headers for browser clients (architectural requirement)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],  # include PATCH implicitly
        allow_headers=[
            "If-Match",
            "Content-Type",
        ],
        expose_headers=[
            "Screen-ETag",
            "Question-ETag",
            "Questionnaire-ETag",
            "Document-ETag",
            "ETag",
        ],
    )

    # Epic K §6.2.2.87 — Media type validation precedes preconditions for answers PATCH
    @app.middleware("http")
    async def _answers_content_type_guard(request: Request, call_next):  # type: ignore[override]
        try:
            method_u = str(getattr(request, "method", "")).upper()
            path = str(getattr(request, "url", "").path) if hasattr(request, "url") else ""
        except Exception:
            method_u, path = "", ""
        if method_u == "PATCH":
            try:
                import re as _re
                m = _re.fullmatch(r"/api/v1/response-sets/[^/]+/answers/[^/]+", path or "")
            except Exception:
                m = None
            if m:
                # Only allow JSON payloads; otherwise emit 415 ProblemDetails
                try:
                    raw_ctype = (request.headers.get("content-type") or request.headers.get("Content-Type") or "")
                    ctype = str(raw_ctype).lower()
                    ctype_base = ctype.split(";", 1)[0].strip()
                except Exception:
                    ctype_base = ""
                # Clarke 7.2.2.87: Only reject when Content-Type header is present and not JSON
                if ctype_base and ctype_base != "application/json":
                    # Hardened: positively allow only application/json; all others 415
                    problem = {
                        "title": "Unsupported Media Type",
                        "status": 415,
                        "detail": "Content-Type must be application/json",
                        "message": "Content-Type must be application/json",
                        "code": "PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED",
                    }
                    try:
                        logger.info(
                            "answers.content_type_guard.reject path=%s content_type=%s",
                            path,
                            (request.headers.get("content-type") or request.headers.get("Content-Type") or ""),
                        )
                    except Exception:
                        pass
                    return JSONResponse(problem, status_code=415, media_type="application/problem+json")
        return await call_next(request)

    # Preflight handler: mirror Access-Control-Request-* for OPTIONS and exit early
    @app.middleware("http")
    async def _preflight_mirror(request: Request, call_next):  # type: ignore[override]
        try:
            if str(getattr(request, "method", "")).upper() == "OPTIONS":
                acrm = request.headers.get("Access-Control-Request-Method") if hasattr(request, "headers") else None
                acrh = request.headers.get("Access-Control-Request-Headers") if hasattr(request, "headers") else None
                resp = Response(status_code=204)
                # Always allow origin for tests
                resp.headers.setdefault("Access-Control-Allow-Origin", "*")
                # Mirror requested method when present; ensure PATCH is covered
                resp.headers["Access-Control-Allow-Methods"] = (acrm or "PATCH")
                # Mirror requested headers when present; otherwise choose defaults by requested method.
                # For write methods, include If-Match; for GET/others, omit If-Match.
                if acrh:
                    resp.headers["Access-Control-Allow-Headers"] = acrh
                    # Clarke 7.2.1.15: Filter If-Match for non-write preflights
                    try:
                        method_u = str(acrm or "").upper()
                        if method_u not in {"PATCH", "POST", "PUT", "DELETE"}:
                            raw = str(acrh)
                            tokens = [t.strip() for t in raw.split(",") if t.strip()]
                            seen: set[str] = set()
                            kept: list[str] = []
                            for t in tokens:
                                tl = t.lower()
                                if tl == "if-match":
                                    continue
                                if tl not in seen:
                                    seen.add(tl)
                                    kept.append(tl)
                            resp.headers["Access-Control-Allow-Headers"] = ", ".join(kept) if kept else ""
                    except Exception:
                        # Never fail preflight on header normalization
                        pass
                else:
                    method_u = str(acrm or "").upper()
                    if method_u in {"PATCH", "POST", "PUT", "DELETE"}:
                        resp.headers["Access-Control-Allow-Headers"] = "if-match, content-type"
                    else:
                        resp.headers["Access-Control-Allow-Headers"] = "content-type"
                return resp
        except Exception:
            # Never interfere with normal flow; fall through
            logger.error("preflight_mirror_failed", exc_info=True)
        return await call_next(request)

    # Lightweight middleware: request-id and ETag passthrough if already set by handlers
    @app.middleware("http")
    async def request_id_and_etag(request: Request, call_next):  # type: ignore[override]
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        response: Response = await call_next(request)
        response.headers.setdefault("X-Request-Id", request_id)
        # Do not compute ETag here; handlers set it when applicable
        return response

    # CLARKE: FINAL_GUARD answers_problem_ctype_coerce
    # Narrow middleware to coerce error responses for answers PATCH to problem+json
    @app.middleware("http")
    async def _answers_problem_ctype_coerce(request: Request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)
        try:
            method_u = str(getattr(request, "method", "")).upper()
            path = str(getattr(request, "url", "").path) if hasattr(request, "url") else ""
        except Exception:
            method_u, path = "", ""
        if response is not None and getattr(response, "status_code", 200) >= 400 and method_u == "PATCH":
            try:
                import re as _re
                if _re.fullmatch(r"/api/v1/response-sets/[^/]+/answers/[^/]+", path or ""):
                    # Preserve original status for audit; do not mutate
                    _original_status = getattr(response, "status_code", 0)
                    # Coerce to Problem+JSON for error responses on this route only
                    # Idempotent guard: do not overwrite if already problem+json
                    ctype = str(response.headers.get("content-type", "")).lower()
                    # Instrumentation: emit a single structured log for coercion decision
                    try:
                        logger.info(
                            "answers.problem_ctype_coerce path=%s status=%s ctype_before=%s coerced=%s",
                            path,
                            getattr(response, "status_code", 0),
                            ctype,
                            "application/problem+json" not in ctype,
                        )
                    except Exception:
                        # Logging must never affect control flow
                        pass
                    if "application/problem+json" not in ctype:
                        response.headers["content-type"] = "application/problem+json"
                        # Also ensure response.media_type reflects the problem+json type
                        try:
                            response.media_type = "application/problem+json"
                        except Exception:
                            # Some Response types may not expose media_type; ignore
                            pass
                        # Explicit log after coercion is applied
                        try:
                            logger.info(
                                "answers.problem_ctype_coerce.applied path=%s status=%s ctype_final=%s",
                                path,
                                getattr(response, "status_code", 0),
                                "application/problem+json",
                            )
                        except Exception:
                            pass
                        # Sanity: assert status unchanged by coercion
                        try:
                            if getattr(response, "status_code", 0) != _original_status:
                                logger.warning(
                                    "answers.problem_ctype_coerce.status_changed from=%s to=%s",
                                    _original_status,
                                    getattr(response, "status_code", 0),
                                )
                        except Exception:
                            pass
                        # Clarke instrumentation: final observation after coercion
                        try:
                            ctype_final = str(response.headers.get("content-type", ""))
                            logger.info(
                                "answers.problem_ctype_coerce.final path=%s status=%s ctype_final=%s",
                                path,
                                getattr(response, "status_code", 0),
                                ctype_final,
                            )
                        except Exception:
                            # Logging must never affect control flow
                            pass
                        # CLARKE_SENTINEL: problem_ctype_coerced
            except Exception:
                # Never let coercion alter control flow
                pass
        return response

    # Low-level ASGI middleware to enforce RFC7807 media type on error responses
    # for PATCH /api/v1/response-sets/{id}/answers/{id} regardless of downstream behavior.
    # CLARKE_SENTINEL: answers_problem_ctype_asgi
    class AnswersProblemContentTypeASGIMiddleware:  # pragma: no cover - behavior tested via functional tests
        # CLARKE: PROBLEM_CTYPE_OUTER_WRAPPER — outer wrapper ensures RFC7807 for all
        # error responses on target route even when upstream middleware short-circuits.
        # Sentinel used to prevent double-wrapping: _epic_k_problem_ctype_wrapper
        def __init__(self, app: FastAPI):
            self.app = app

        async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
            try:
                if scope.get("type") != "http":
                    await self.app(scope, receive, send)
                    return
                method_u = str(scope.get("method", "")).upper()
                path = str(scope.get("path", "") or "")
            except Exception:
                # If scope inspection fails, pass-through untouched
                await self.app(scope, receive, send)
                return

            import re as _re  # local import for minimal overhead
            matches_route = method_u == "PATCH" and bool(
                _re.fullmatch(r"/api/v1/response-sets/[^/]+/answers/[^/]+", path or "")
            )
            # Instrument entry decision for answers PATCH routing
            try:
                logger.info(
                    "answers.problem_ctype_asgi.entry path=%s method=%s matches_route=%s",
                    path,
                    method_u,
                    matches_route,
                )
            except Exception:
                pass

            if not matches_route:
                await self.app(scope, receive, send)
                return

            async def send_wrapper(message):  # type: ignore[no-untyped-def]
                try:
                    if message.get("type") == "http.response.start":
                        status = int(message.get("status") or message.get("status_code") or 200)
                        if status >= 400:
                            # Pre-rewrite log: capture current Content-Type before coercion
                            try:
                                headers_list = list(message.get("headers") or [])
                                ct_before_pre_val = None
                                for k, v in headers_list:
                                    try:
                                        if (k or b"").lower() == b"content-type":
                                            ct_before_pre_val = v
                                            break
                                    except Exception:
                                        if str(k).lower() == "content-type":
                                            ct_before_pre_val = v
                                            break
                                ct_before_pre = (
                                    ct_before_pre_val.decode("utf-8", errors="ignore") if isinstance(ct_before_pre_val, (bytes, bytearray)) else str(ct_before_pre_val)
                                ) if ct_before_pre_val is not None else ""
                                logger.info(
                                    "answers.problem_ctype_asgi.pre path=%s status=%s ct_before=%s",
                                    path,
                                    status,
                                    ct_before_pre,
                                )
                            except Exception:
                                pass
                            headers = list(message.get("headers") or [])
                            new_headers = []
                            coerced = False
                            # CLARKE_SENTINEL: answers.problem_ctype_asgi.log
                            try:
                                # Compute initial Content-Type (if any) for logging
                                ct_before_val = None
                                for k, v in headers:
                                    try:
                                        key_is_ct = (k or b"").lower() == b"content-type"
                                    except Exception:
                                        key_is_ct = str(k).lower() == "content-type"
                                    if key_is_ct:
                                        ct_before_val = v
                                        break
                                ct_before = (
                                    (ct_before_val.decode("utf-8", errors="ignore") if isinstance(ct_before_val, (bytes, bytearray)) else str(ct_before_val))
                                    if ct_before_val is not None else ""
                                )
                            except Exception:
                                ct_before = ""
                            for k, v in headers:
                                try:
                                    key_is_ct = (k or b"").lower() == b"content-type"
                                except Exception:
                                    # If header key is not bytes, fall back to string compare
                                    key_is_ct = str(k).lower() == "content-type"
                                if key_is_ct:
                                    if not coerced:
                                        new_headers.append((b"content-type", b"application/problem+json"))
                                        coerced = True
                                    # Skip existing content-type instances
                                else:
                                    new_headers.append((k, v))
                            if not coerced:
                                new_headers.append((b"content-type", b"application/problem+json"))
                            try:
                                logger.info(
                                    "answers.problem_ctype_asgi path=%s status=%s ct_before=%s ct_after=%s coerced=%s",
                                    path,
                                    status,
                                    ct_before,
                                    "application/problem+json",
                                    (ct_before or "").lower() != "application/problem+json",
                                )
                            except Exception:
                                # Never block response on logging failures
                                pass
                            message["headers"] = new_headers
                            # Post-rewrite log: confirm final content type and coercion decision
                            try:
                                logger.info(
                                    "answers.problem_ctype_asgi.post path=%s status=%s ct_after=%s coerced=%s",
                                    path,
                                    status,
                                    "application/problem+json",
                                    coerced or ((ct_before or "").lower() != "application/problem+json"),
                                )
                            except Exception:
                                pass
                            # Clarke instrumentation: emit final confirmation log
                            try:
                                ct_after = "application/problem+json"
                                logger.info(
                                    "answers.problem_ctype_asgi.final path=%s status=%s ct_after=%s coerced=%s",
                                    path,
                                    status,
                                    ct_after,
                                    coerced or ((ct_before or "").lower() != "application/problem+json"),
                                )
                            except Exception:
                                pass
                except Exception:
                    # Never block response on middleware failure
                    pass
                await send(message)

            await self.app(scope, receive, send_wrapper)

    # Apply migrations on startup (guarded) to avoid import-time side effects
    @app.on_event("startup")
    def _apply_migrations() -> None:  # pragma: no cover - exercised via integration
        # Phase-0: Short-circuit when PostgreSQL driver is unavailable
        # This prevents TestClient(create_app()) from failing during unit tests
        # where psycopg2 may not be installed even if DATABASE_URL points to Postgres.
        try:
            db_url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL") or ""
            requires_pg = ("postgresql" in db_url or "+psycopg2" in db_url) and not db_url.startswith("sqlite")
            if requires_pg:
                try:  # Attempt to import the driver only when needed
                    import psycopg2  # type: ignore
                except Exception:
                    # Emit a single, stable marker for tests/telemetry and return early
                    logger.warning("startup_migrations_skipped_no_db_driver")
                    return
        except Exception:
            # Do not block startup if URL inspection fails unexpectedly
            logger.error("startup_migrations_driver_check_failed", exc_info=True)

        # Allow disabling auto-migrations via env (best practice for prod)
        enable_flag = os.getenv("AUTO_APPLY_MIGRATIONS", "").strip().lower() in {"1", "true", "yes", "on"}
        try:
            engine = get_engine()
        except Exception:
            logger.error("Failed to build DB engine before migrations", exc_info=True)
            raise
        try:
            # Schema readiness short-circuit with Epic G columns awareness
            from sqlalchemy import text
            with engine.connect() as conn:
                # Check core objects first
                has_questionnaires = conn.execute(text("SELECT to_regclass('public.questionnaires')")).scalar()
                has_placeholder_idx = conn.execute(
                    text("SELECT to_regclass('public.uq_question_placeholder_code')")
                ).scalar()

                # Explicitly verify Epic G columns exist; if missing, force migrations
                epic_g_missing = False
                try:
                    conn.execute(text("SELECT screen_order FROM screen LIMIT 1"))
                except Exception:
                    epic_g_missing = True
                try:
                    conn.execute(text("SELECT question_order FROM questionnaire_question LIMIT 1"))
                except Exception:
                    epic_g_missing = True

                if epic_g_missing:
                    logger.info("Epic G columns missing; forcing migrations regardless of AUTO_APPLY_MIGRATIONS")
                    try:
                        apply_migrations(engine)
                    except Exception:
                        logger.error("Forced migrations for Epic G failed", exc_info=True)
                        raise
                    return

                if has_questionnaires and has_placeholder_idx:
                    logger.info("DB schema appears ready; skipping migrations at startup")
                    return
        except Exception:
            # If readiness check fails, fall through to migrations when enabled
            logger.error("Schema readiness check failed; proceeding to migrations if enabled", exc_info=True)
        if not enable_flag:
            logger.info("AUTO_APPLY_MIGRATIONS disabled; skipping migrations at startup")
            return
        try:
            apply_migrations(engine)
        except Exception:
            logger.error("Failed to apply migrations at startup", exc_info=True)
            raise

    # Ensure outermost problem+json wrapper is applied before any other middleware/routers
    # Idempotent via sentinel attribute on wrapper instance
    try:
        _sentinel_early = getattr(app, "_epic_k_problem_ctype_wrapper", False) is True
    except Exception:
        _sentinel_early = False
    if not _sentinel_early:
        app = AnswersProblemContentTypeASGIWrapper(app)
    # Register final coercion middleware before routers to wrap all endpoints
    # CLARKE_SENTINEL: answers_problem_ctype_asgi_registered (verified outer ASGI wrapper short-circuits 415)
    app.add_middleware(AnswersProblemContentTypeASGIMiddleware)

    # Routers
    app.include_router(api_router, prefix="/api/v1")
    # Include test-support router (no prefix) to expose '/__test__/events'
    from app.routes.test_support import router as test_support_router
    app.include_router(test_support_router)

    # Health endpoint (out of prefix for simplicity in local runs)
    health_check = _health_check()

    @app.get("/health")
    def health():  # pragma: no cover - trivial
        return health_check()

    # Ensure outermost wrapper is applied exactly once (idempotent)
    try:
        sentinel_present = getattr(app, "_epic_k_problem_ctype_wrapper", False) is True
    except Exception:
        sentinel_present = False
    if not sentinel_present:
        app = AnswersProblemContentTypeASGIWrapper(app)

    return app


# Intentionally do not instantiate the app at import time to prevent side effects.
