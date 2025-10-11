"""QuestionKind enumeration for allowed single-value question types (Epic E).

Provides a simple constants container instead of an Enum to keep imports
lightweight in architectural tests.
"""

from __future__ import annotations


class QuestionKind:
    SHORT_STRING = "short_string"
    LONG_TEXT = "long_text"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM_SINGLE = "enum_single"


__all__ = ["QuestionKind"]

