"""Type-aware validation for answer upserts.

This module provides minimal validation used by autosave to ensure payload
shape is coherent. Full rules by answer_kind are kept in JSON Schemas under
`docs/schemas/AnswerUpsert.schema.json` and enforced at the API layer.
"""

from __future__ import annotations

from typing import Any, Dict


class HamiltonValidationError(ValueError):
    pass

# Backward compatibility export to avoid breaking external callers
ValidationError = HamiltonValidationError


def validate_answer_upsert(payload: Dict[str, Any]) -> None:
    """Basic coherence checks for an AnswerUpsert payload.

    - Either `value` or `option_id` must be provided
    - Reject unknown extra keys (best-effort)
    """

    if not isinstance(payload, dict):  # pragma: no cover - defensive
        raise HamiltonValidationError("payload must be an object")
    allowed = {"value", "option_id"}
    extra = set(payload.keys()) - allowed
    if extra:
        raise HamiltonValidationError(f"unexpected keys: {sorted(extra)}")

    if payload.get("value") is None and not payload.get("option_id"):
        raise HamiltonValidationError("either value or option_id required")


def validate_kind_value(kind: str, value: Any) -> None:
    """Validate a value against a simple answer kind contract.

    Only enforces primitive kinds used by integration scenarios.
    """
    if kind == "number" and not isinstance(value, (int, float)):
        raise HamiltonValidationError("type_mismatch: expected number for $.value")
    if kind == "boolean" and not isinstance(value, bool):
        raise HamiltonValidationError("type_mismatch: expected boolean for $.value")
