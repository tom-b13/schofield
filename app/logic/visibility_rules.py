"""Visibility rule evaluation helpers for Conditional Visibility (Epic I).

Centralizes equality-based visibility checks and set computations used by
route handlers to avoid duplication and drift.
"""

from __future__ import annotations

from typing import Iterable


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
    targets = {str(x) for x in visible_if_values}
    return parent_value in targets


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
        pv = parent_values.get(parent_id)
        if is_child_visible(pv, vis_list):
            visible.add(qid)
    return visible

