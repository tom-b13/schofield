"""FastAPI application package init for EPIC-B — Questionnaire Service.

This package exposes a small FastAPI application factory used by the
Questionnaire Service. It wires only cross-cutting middleware (request-id
and ETag passthrough) and mounts the API routers. Business logic lives in
`app/logic/` and route handlers in `app/routes/`.
"""

from __future__ import annotations

from app.main import create_app

__all__ = ["create_app"]
