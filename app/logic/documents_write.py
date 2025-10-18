"""Write helpers for Documents routes (architectural extraction).

Provides small, single-purpose helpers to keep route handlers free of
string manipulation and normalization logic.
"""

from __future__ import annotations

from typing import Any


def normalize_title(value: Any) -> str:
    """Return a sanitized title string or empty string if invalid."""
    try:
        return str(value).strip()
    except Exception:
        return ""


__all__ = ["normalize_title"]

