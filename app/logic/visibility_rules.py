"""Visibility rule evaluation helpers for Conditional Visibility (Epic I).

Centralizes equality-based visibility checks and set computations used by
route handlers to avoid duplication and drift.
"""

from __future__ import annotations

from typing import Iterable
import logging

logger = logging.getLogger(__name__)


def is_child_visible(parent_value: str | None, visible_if_values: Iterable | None) -> bool:
    """Return True if a child should be visible given the parent's canonical value.

    Visibility is equality-based: the child is visible only when the parent's
    canonical value is present in the configured list of visible-if values.
    Empty or None lists do not make a child visible.
    """
    if parent_value is None:
        return False
    if not visible_if_values:
        return False
    # Normalize boolean-like tokens to canonical 'true'/'false' strings for both
    # the parent value and the target list to ensure robust equality checks.
    def _canon(tok: object) -> str:
        try:
            if isinstance(tok, bool):
                return "true" if tok else "false"
            s = str(tok)
            return s.lower() if s.lower() in {"true", "false"} else s
        except Exception:
            return str(tok)

    pv_norm = _canon(parent_value)
    targets = {_canon(x) for x in visible_if_values}
    return pv_norm in targets


def compute_visible_set(
    rules: dict[str, tuple[str | None, list | None]],
    parent_values: dict[str, str | None],
) -> set[str]:
    """Compute the set of visible question_ids for a screen.

    - Base questions (no parent) are always visible.
    - Child questions are visible only if their parent's canonical value matches
      one of the configured visible-if values.
    """
    visible: set[str] = set()
    for qid, (parent_id, vis_list) in rules.items():
        if parent_id is None:
            visible.add(qid)
            continue
        # Clarke: ensure parent id is coerced to str for parent_values lookup
        pv = parent_values.get(str(parent_id))
        if is_child_visible(pv, vis_list):
            visible.add(qid)
    return visible


def filter_visible_questions(
    rules: dict[str, tuple[str | None, list | None]],
    parent_values: dict[str, str | None],
) -> set[str]:
    """Thin named wrapper that returns the subset of visible question_ids.

    Exists to satisfy the architectural requirement of an explicit filtering
    step executed prior to screen assembly.
    """
    return compute_visible_set(rules, parent_values)


def validate_visibility_compatibility(parent_answer_kind: str, visible_if_value: object) -> None:
    """Validate that the provided visible_if_value is compatible with parent kind.

    - Interprets answer kinds per AnswerKind schema; only boolean parents accept
      visible_if_value tokens, which must be one of ['true','false'] (case-insensitive).
    - Raises ValueError with a code token when incompatible; returns None when OK.
    """
    kind = (parent_answer_kind or "").strip().lower() if isinstance(parent_answer_kind, str) else ""
    if kind in {"bool", "boolean", "yesno"}:
        # Accept lists and scalars; normalize to boolean tokens
        def _canon(val: object) -> list[str] | None:
            if val is None:
                return None
            if isinstance(val, bool):
                return ["true" if val else "false"]
            try:
                s = str(val).strip().lower()
            except Exception:
                s = str(val)
            if isinstance(val, (list, tuple)):
                out: list[str] = []
                for item in val:
                    if isinstance(item, bool):
                        out.append("true" if item else "false")
                    else:
                        t = str(item).strip().lower()
                        if t in {"true", "false"}:
                            out.append(t)
                        else:
                            return None
                return out if out else None
            return [s] if s in {"true", "false"} else None
        if _canon(visible_if_value) is None:
            raise ValueError("incompatible_with_parent_answer_kind")
        return None
    # Non-boolean parent: only accept null visible_if_value
    if visible_if_value is None:
        return None
    raise ValueError("incompatible_with_parent_answer_kind")


def canonicalize_boolean_visible_if_list(value: object | None) -> list[str] | None:
    """Canonicalize a boolean visible_if value into a list of 'true'/'false' strings.

    - Accepts scalars or iterables.
    - Returns None when the value cannot be canonicalized.
    - Logs coercion errors at ERROR with context, does not raise.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return ["true" if value else "false"]
    try:
        s = str(value).strip().lower()
        if s in {"true", "false"}:
            return [s]
    except Exception:
        logger.error("canonicalize_boolean_visible_if_list string coercion failed value=%r", value, exc_info=True)
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if isinstance(item, bool):
                out.append("true" if item else "false")
            else:
                t = str(item).strip().lower()
                if t in {"true", "false"}:
                    out.append(t)
                else:
                    return None
        return out if out else None
    return None
