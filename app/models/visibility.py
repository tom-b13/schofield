"""Visibility-related reusable types."""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class NowVisible(BaseModel):
    question: str
    answer: Optional[str] = None


__all__ = ["NowVisible"]

