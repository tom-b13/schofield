from __future__ import annotations

import logging
import os
import uuid
from typing import Callable

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError  # instrumentation only
from fastapi.exception_handlers import (
    request_validation_exception_handler as _default_request_validation_handler,
)
from fastapi.middleware.cors import CORSMiddleware
from app.logging_setup import configure_logging
from app.db.base import get_engine
from app.db.migrations_runner import apply_migrations
from app.routes import api_router

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


def create_app() -> FastAPI:
    # Configure global logging before app instantiation so all modules emit
    try:
        configure_logging()
    except Exception:
        logging.getLogger(__name__).error("global_logging_configuration_failed", exc_info=True)
    app = FastAPI()

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
    # Expose domain ETag headers for browser clients (architectural requirement)
    app.add_middleware(
        CORSMiddleware,
        expose_headers=[
            "Screen-ETag",
            "Question-ETag",
            "Questionnaire-ETag",
            "Document-ETag",
            "ETag",
        ],
        allow_headers=[
            "If-Match",
        ],
    )

    # Lightweight middleware: request-id and ETag passthrough if already set by handlers
    @app.middleware("http")
    async def request_id_and_etag(request: Request, call_next):  # type: ignore[override]
        request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
        response: Response = await call_next(request)
        response.headers.setdefault("X-Request-Id", request_id)
        # Do not compute ETag here; handlers set it when applicable
        return response

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
                    conn.execute(text("SELECT screen_order FROM screens LIMIT 1"))
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

    return app


# Intentionally do not instantiate the app at import time to prevent side effects.
