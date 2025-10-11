"""Test support routes.

Minimal test-only endpoints used by integration tests to observe
domain events that are not included inline in 204 responses.

Skeleton only — no business logic.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from app.logic import events as domain_events

router = APIRouter()


@router.get("/__test__/events")
def get_events() -> JSONResponse:  # noqa: D401 - simple skeleton
    """Return buffered domain events for tests (skeleton)."""
    evts = domain_events.get_buffered_events(clear=True)
    return JSONResponse(content={"events": evts}, status_code=200)
