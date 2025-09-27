from __future__ import annotations

import logging
import os
import uuid
from typing import Callable

from fastapi import FastAPI, Request, Response
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
    app = FastAPI()

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
        # Allow disabling auto-migrations via env (best practice for prod)
        enable_flag = os.getenv("AUTO_APPLY_MIGRATIONS", "").strip().lower() in {"1", "true", "yes", "on"}
        try:
            engine = get_engine()
        except Exception:
            logger.error("Failed to build DB engine before migrations", exc_info=True)
            raise
        try:
            # Schema readiness short-circuit: if core objects exist, skip migrations
            from sqlalchemy import text
            with engine.connect() as conn:
                # Check a core table and a core index as sentinels
                has_questionnaires = conn.execute(text("SELECT to_regclass('public.questionnaires')")).scalar()
                has_placeholder_idx = conn.execute(
                    text("SELECT to_regclass('public.uq_question_placeholder_code')")
                ).scalar()
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

    # Health endpoint (out of prefix for simplicity in local runs)
    health_check = _health_check()

    @app.get("/health")
    def health():  # pragma: no cover - trivial
        return health_check()

    return app


# Intentionally do not instantiate the app at import time to prevent side effects.
