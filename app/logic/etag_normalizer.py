"""ETag/If-Match normaliser (Phase-0).

Provides a canonical weak ETag rendering for comparison and diagnostics.
Accepts bare token, quoted token, and weak validator forms as equivalent
inputs and returns a canonical weak-quoted value: W/"<hex>".
"""

from __future__ import annotations

from typing import Optional

from app.logic.etag import normalize_if_match as _normalize_token


def normalise_if_match(value: str | None) -> str | None:
    """Return canonical weak-quoted representation for an If-Match value.

    - Accepts None/blank -> returns None
    - Accepts '*': returns '*'
    - For any other value, strips weak prefix and quotes using shared
      normaliser, then re-wraps as weak quoted: W/"<token>".
    """
    token = _normalize_token(value)
    if not token:
        return None
    if token == "*":
        return "*"
    return f'W/"{token}"'


__all__ = ["normalise_if_match"]
