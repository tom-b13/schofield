"""Internal diagnostics endpoints used by integration tests.

These routes are not part of the public API. They allow test steps to
emit structured logs that appear in the server log for cross-process
observability during integration runs.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import logging

from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal")
# Secondary router to accept authoring-prefixed internal logs used by some tests
authoring_router = APIRouter(prefix="/authoring/internal")


class LogPayload(BaseModel):
    event: str
    message: Optional[str] = None
    fields: Optional[Dict[str, Any]] = None


@router.post("/log")
async def internal_log(p: LogPayload) -> Dict[str, str]:
    try:
        evt = p.event or "test.instrument"
    except Exception:
        evt = "test.instrument"
    try:
        logger.info("%s", evt)
        if p.message:
            logger.info("%s", p.message)
        if isinstance(p.fields, dict):
            # Log fields in a stable key order for readability
            for k in sorted(p.fields.keys()):
                try:
                    logger.info("%s=%s", k, p.fields[k])
                except Exception:
                    logger.info("%s=<unprintable>", k)
    except Exception:
        logger.error("internal_log_emit_failed", exc_info=True)
    return {"status": "ok"}


@authoring_router.post("/log")
async def internal_log_authoring(p: LogPayload) -> Dict[str, str]:
    # Delegate to the same implementation
    return await internal_log(p)


__all__ = ["router", "authoring_router"]
