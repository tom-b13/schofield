"""Static transform registry for Epic D catalog."""

from __future__ import annotations

from typing import List, Mapping


TRANSFORM_REGISTRY: List[Mapping[str, str]] = [
    {"name": "UPPERCASE", "title": "Uppercase"},
    {"name": "LOWERCASE", "title": "Lowercase"},
]

__all__ = ["TRANSFORM_REGISTRY"]

