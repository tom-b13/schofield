"""Pre-body preconditions middleware (Epic K Phase-0).

Intercepts write routes and enforces missing If-Match semantics before any
dependency evaluation or request body parsing occurs. Emits Problem+JSON
responses with canonical PRE_* codes via problem_factory.
"""

from __future__ import annotations

from typing import Iterable, Tuple

from fastapi import FastAPI

from app.logic.problem_factory import problem_pre_if_match_missing


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
        if not (is_answers or is_documents):
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

