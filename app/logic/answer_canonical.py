"""Canonicalization helpers for stored answer values.

Provides a single function to normalize persisted answer columns into a
stable string representation used for visibility comparisons.
"""

from __future__ import annotations

from typing import Optional


def canonicalize_answer_value(
    value_text: str | None,
    value_number: float | int | None,
    value_bool: bool | None,
) -> Optional[str]:
    """Return a stable string representation for stored answer columns.

    - Booleans -> "true" / "false"
    - Numbers  -> integer form when integral, else decimal string
    - Text     -> as-is string
    - None     -> None
    """
    if value_bool is not None:
        return "true" if bool(value_bool) else "false"
    if value_text is not None:
        return str(value_text)
    if value_number is not None:
        try:
            f = float(value_number)
            if float(int(f)) == f:
                return str(int(f))
            return str(f)
        except Exception:
            return str(value_number)
    return None

