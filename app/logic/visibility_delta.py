"""Helpers to compute visibility deltas and suppressed answers.

Exposes a single function that computes now_visible, now_hidden, and the list
of suppressed answers using a caller-provided probe for answer existence.
"""

from __future__ import annotations

from typing import Callable, Iterable, List, Tuple, Any

from app.models.visibility import NowVisible


def compute_visibility_delta(
    pre_visible: Iterable[str],
    post_visible: Iterable[str],
    has_answer: Callable[[str], bool],
) -> Tuple[list, list[str], list[str]]:
    """Compute visibility delta and suppressed answers.

    - now_visible: questions newly visible (in post but not in pre)
    - now_hidden: questions newly hidden (in pre but not in post)
    - suppressed_answers: subset of now_hidden that currently have stored answers

    The has_answer callable should return True if a given question_id currently
    has a stored answer for the active response set. Exceptions raised by the
    callable are allowed to propagate to preserve caller logging semantics.
    """
    def _coerce_id(item: Any) -> str | None:
        # Defensive normalization: accept dicts with 'question' or 'question_id'
        try:
            if isinstance(item, dict):
                return (
                    item.get("question")
                    or item.get("question_id")
                    or (str(item.get("id")) if item.get("id") else None)
                )
            # tuples/lists: treat first element as id if it's a string-like
            if isinstance(item, (list, tuple)) and item:
                head = item[0]
                return str(head)
            # primitives
            return str(item)
        except Exception:
            return None

    pre_set = {qid for qid in (_coerce_id(x) for x in pre_visible) if qid}
    post_set = {qid for qid in (_coerce_id(x) for x in post_visible) if qid}

    # Return now_visible as a list[str] of question_id UUIDs for consistency
    # with Epic D/I contracts and downstream JSONPath assertions.
    _new_visible_ids = sorted(list(post_set - pre_set))
    # Guarantee both arrays are lists of UUID strings for downstream JSONPath
    now_visible = [str(qid) for qid in _new_visible_ids]
    # Guarantee now_hidden reflects pre - post on question_id strings
    now_hidden = [str(qid) for qid in sorted(list(pre_set - post_set))]

    suppressed_answers: List[str] = []
    for qid in now_hidden:
        if has_answer(qid):
            suppressed_answers.append(qid)

    return now_visible, now_hidden, suppressed_answers
