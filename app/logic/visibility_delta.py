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
        """Normalize various shapes to a question_id string.

        Accepts dicts with 'question'/'question_id' (or nested), tuple/list first item,
        and primitives. Trims whitespace and ignores empty/None values.
        """
        try:
            if isinstance(item, dict):
                val = item.get("question") or item.get("question_id") or item.get("id")
                # Handle nested dicts: {question: {id: ...}}
                if isinstance(val, dict):
                    val = val.get("question_id") or val.get("id")
                return (str(val).strip() or None) if val is not None else None
            if isinstance(item, (list, tuple)) and item:
                head = item[0]
                return (str(head).strip() or None) if head is not None else None
            if item is None:
                return None
            sid = str(item).strip()
            return sid or None
        except Exception:
            return None

    # Normalize any incoming iterable items (dicts/tuples/primitives) to string ids
    pre_set = {qid for qid in (_coerce_id(x) for x in pre_visible) if qid}
    post_set = {qid for qid in (_coerce_id(x) for x in post_visible) if qid}

    # Return now_visible as a list[str] of question_id UUIDs for consistency
    # with Epic D/I contracts and downstream JSONPath assertions.
    _new_visible_ids = sorted(list(post_set - pre_set))
    # Guarantee both arrays are lists of UUID strings for downstream JSONPath
    now_visible = [str(qid) for qid in _new_visible_ids]
    # Guarantee now_hidden reflects pre - post on question_id strings
    now_hidden = [str(qid) for qid in sorted(list(pre_set - post_set))]

    # Suppressed answers include newly hidden questions that currently have
    # stored answers. Probe via provided callable so callers can inject a
    # repository-backed existence check bound to the active response set.
    suppressed_answers: List[str] = []
    for qid in now_hidden:
        try:
            if bool(has_answer(qid)):
                suppressed_answers.append(qid)
        except Exception:
            # On probe failure, act conservatively and do not mark as suppressed
            # (callers may separately log/handle the underlying issue).
            continue

    return now_visible, now_hidden, suppressed_answers
