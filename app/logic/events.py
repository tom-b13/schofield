"""Domain event constants and publisher.

Defines event type constants and a simple publish() callable used by
save and delete flows.
"""

from __future__ import annotations

from typing import Any, Dict, List
import logging

logger = logging.getLogger(__name__)

RESPONSE_SAVED = "response.saved"
RESPONSE_SET_DELETED = "response_set.deleted"


def publish(event_type: str, payload: Dict[str, Any]) -> None:  # pragma: no cover - side-effect only
    """Publish a domain event.

    In this minimal implementation, we log the event for observability.
    """
    logger.info("event_publish type=%s payload=%s", event_type, payload)
    # Buffer events in-memory for test observation
    EVENT_BUFFER.append({"type": event_type, "payload": payload})


# In-memory buffer for domain events (test-only visibility)
EVENT_BUFFER: List[Dict[str, Any]] = []


def get_buffered_events(clear: bool = True) -> List[Dict[str, Any]]:
    """Return buffered domain events; optionally clear the buffer."""
    events = list(EVENT_BUFFER)
    if clear:
        EVENT_BUFFER.clear()
    return events

__all__ = [
    "RESPONSE_SAVED",
    "RESPONSE_SET_DELETED",
    "publish",
    "get_buffered_events",
    "EVENT_BUFFER",
]
