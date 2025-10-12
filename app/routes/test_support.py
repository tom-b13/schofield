"""Test support routes.

Provides test-only endpoints used by integration tests to reset
in-memory state and to observe buffered domain events. Paths and
behaviours are preserved for architectural compliance.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response
import logging

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/__test__/reset-state", summary="Test-only reset state")
def reset_state() -> Response:
    """Clear in-memory stores and caches for a clean test precondition.

    This endpoint exists only for integration testing and returns 204 with no body.
    """
    # Clear domain event buffer
    try:
        from app.logic import events as _events

        _events.EVENT_BUFFER.clear()
    except Exception:
        logger.error("Failed to clear EVENT_BUFFER", exc_info=True)

    # Clear in-memory state used across Epics C/D/E
    try:
        from app.logic import inmemory_state as _mem

        _mem.DOCUMENTS_STORE.clear()
        _mem.DOCUMENT_BLOBS_STORE.clear()
        _mem.IDEMPOTENCY_STORE.clear()
        _mem.PLACEHOLDERS_BY_ID.clear()
        _mem.PLACEHOLDERS_BY_QUESTION.clear()
        _mem.IDEMPOTENT_BINDS.clear()
        _mem.IDEMPOTENT_RESULTS.clear()
        _mem.ANSWERS_IDEMPOTENT_RESULTS.clear()
        _mem.ANSWERS_LAST_SUCCESS.clear()
        _mem.QUESTION_MODELS.clear()
        _mem.QUESTION_ETAGS.clear()
    except Exception:
        logger.error("Failed to clear in-memory state", exc_info=True)

    # Clear repository-level in-memory registries if present
    try:
        import app.logic.repository_response_sets as _rs

        reg = getattr(_rs, "_INMEM_RS_REGISTRY", None)
        if isinstance(reg, set):
            reg.clear()
    except Exception:
        logger.error("Failed to clear response set registry", exc_info=True)

    # Clear answer repository in-memory fallbacks
    try:
        import app.logic.repository_answers as _ans

        getattr(_ans, "_INMEM_ANSWERS", {}).clear()
        getattr(_ans, "_SCREEN_VERSIONS", {}).clear()
    except Exception:
        logger.error("Failed to clear answers repository state", exc_info=True)

    return Response(status_code=204)


@router.get("/__test__/events", summary="Test-only events feed")
def get_test_events():
    """Expose buffered domain events for integration assertions.

    Does not clear the buffer; returns a JSON array of event objects.
    """
    from app.logic.events import get_buffered_events

    events = get_buffered_events(clear=False)
    return JSONResponse(events, status_code=200, media_type="application/json")


__all__ = ["router", "reset_state", "get_test_events"]
