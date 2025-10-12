"""Pydantic models for Epic E response bodies."""

from __future__ import annotations

from typing import Any, List
from pydantic import BaseModel
from app.models.visibility import NowVisible


class VisibilityDelta(BaseModel):
    now_visible: List[str]
    now_hidden: List[str]


class ScreenView(BaseModel):
    screen_key: str
    questions: list
    etag: str | None = None


class ScreenAlias(BaseModel):
    screen_key: str
    screen_id: str | None = None


class ScreenViewEnvelope(BaseModel):
    """Envelope for GET screen responses.

    Matches the contract expected by integration: include both
    `screen_view` and a `screen` alias object.
    """
    screen_view: ScreenView
    screen: ScreenAlias | None = None


class SavedMeta(BaseModel):
    question_id: str
    state_version: int


class SavedResult(BaseModel):
    saved: bool
    etag: str
    # Keep screen_view for downstream consumers; optional for PATCH response schema
    screen_view: ScreenView | None = None
    visibility_delta: VisibilityDelta | None = None
    suppressed_answers: list[str] | None = None
    # Ensure FastAPI includes domain events on 200 responses
    events: list | None = None


class BatchResult(BaseModel):
    items: list


class Events(BaseModel):
    events: list


__all__ = [
    "NowVisible",
    "VisibilityDelta",
    "ScreenView",
    "ScreenViewEnvelope",
    "ScreenAlias",
    "SavedMeta",
    "SavedResult",
    "BatchResult",
    "Events",
]
