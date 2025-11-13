"""Pre-body preconditions middleware (Epic K Phase-0).

Intercepts write routes and enforces basic pre-body checks before any
dependency evaluation or request body parsing occurs.

Enforcements:
- 415 PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED for non-JSON Content-Type on
  answers/documents write routes (base type check only)
- 428 PRE_IF_MATCH_MISSING for missing/blank If-Match on the same routes

Notes:
- Invalid If-Match format, token normalization, and mismatch handling are
  owned by the guard (app.guards.precondition). This middleware performs no
  comparison and emits no success headers.
"""

from __future__ import annotations

from typing import Iterable, Tuple

from fastapi import FastAPI

from app.logic.problem_factory import (
    problem_pre_if_match_missing,
    problem_pre_request_content_type_unsupported,
)


class PreconditionsMiddleware:  # pragma: no cover - exercised by functional tests
    """ASGI middleware enforcing pre-body preconditions for write routes.

    - Missing/blank If-Match on answers/documents writes → 428 PRE_IF_MATCH_MISSING
    - Executes before dependencies/guards and before body parsing
    """

    def __init__(self, app: FastAPI):
        self.app = app

    async def __call__(self, scope, receive, send):  # type: ignore[no-untyped-def]
        # Only HTTP requests are relevant
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method") or "").upper()
        path = str(scope.get("path") or "")

        # Target only write routes where If-Match is required per Epic K
        if method not in {"PATCH", "POST", "DELETE", "PUT"}:
            await self.app(scope, receive, send)
            return

        # Minimal path matching for Phase-0: answers and documents endpoints
        import re as _re

        is_answers = bool(_re.fullmatch(r"/api/v1/response-sets/[^/]+/answers/[^/]+", path))
        is_documents = bool(_re.fullmatch(r"/api/v1/documents(/.*)?", path))
        # Exempt generic documents create endpoint from If-Match presence check
        is_documents_create = bool(_re.fullmatch(r"/api/v1/documents/?", path)) and method == "POST"
        if not (is_answers or is_documents) or is_documents_create:
            await self.app(scope, receive, send)
            return

        # Extract headers from ASGI scope (list[tuple[bytes, bytes]])
        def _headers(scope_headers: Iterable[Tuple[bytes, bytes]]):
            for k, v in (scope_headers or []):
                try:
                    yield (k.decode("latin-1").lower(), v.decode("latin-1"))
                except Exception:
                    yield (str(k).lower(), str(v))

        headers = dict(_headers(scope.get("headers") or []))

        # 1) Content-Type base enforcement (answers/documents writes only). Guard must not run before this.
        # Only enforce when a Content-Type header is present and base type is not application/json.
        raw_ctype = headers.get("content-type", "")
        ctype_base = str(raw_ctype).split(";", 1)[0].strip().lower() if raw_ctype else ""
        if ctype_base and ctype_base != "application/json":
            problem = problem_pre_request_content_type_unsupported()
            body = (
                (str(problem)).encode("utf-8")
                if not isinstance(problem, dict)
                else (
                    ("{" + ",".join(
                        [
                            f'"{k}":' + (f'"{v}"' if isinstance(v, str) else str(v))
                            for k, v in problem.items()
                        ]
                    ) + "}").encode("utf-8")
                )
            )
            await send(
                {
                    "type": "http.response.start",
                    "status": 415,
                    "headers": [(b"content-type", b"application/problem+json")],
                }
            )
            await send({"type": "http.response.body", "body": body, "more_body": False})
            return

        # 2) If-Match presence enforcement (missing/blank → 428)
        if_match_val = headers.get("if-match")
        # Treat missing or blank values as missing
        if not if_match_val or not str(if_match_val).strip():
            problem = problem_pre_if_match_missing()
            body = (
                (str(problem)).encode("utf-8")
                if not isinstance(problem, dict)
                else (
                    ("{" + ",".join(
                        [
                            f'"{k}":' + (f'"{v}"' if isinstance(v, str) else str(v))
                            for k, v in problem.items()
                        ]
                    ) + "}").encode("utf-8")
                )
            )
            await send(
                {
                    "type": "http.response.start",
                    "status": 428,
                    "headers": [(b"content-type", b"application/problem+json")],
                }
            )
            await send({"type": "http.response.body", "body": body, "more_body": False})
            return

        # Preconditions satisfied; continue to downstream app
        await self.app(scope, receive, send)


# CLARKE: FINAL_GUARD <preconditions-mw>
