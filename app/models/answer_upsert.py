"""Pydantic model for answer upsert payloads.

Extracted from route module to satisfy architectural separation. This module
declares the payload structure used by answer write routes without coupling it
to the route implementation file.
"""

from __future__ import annotations

from pydantic import BaseModel


class AnswerUpsertModel(BaseModel):
    screen_key: str | None = None
    value: str | int | float | bool | None = None
    # Typed aliases to preserve client-provided types when present
    value_bool: bool | None = None
    value_number: float | int | None = None
    value_text: str | None = None
    option_id: str | None = None
    clear: bool | None = None


__all__ = ["AnswerUpsertModel"]
