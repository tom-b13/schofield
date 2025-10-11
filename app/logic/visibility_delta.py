"""Helpers to compute visibility deltas and suppressed answers.

Exposes a single function that computes now_visible, now_hidden, and the list
of suppressed answers using a caller-provided probe for answer existence.
"""

from __future__ import annotations

from typing import Callable, Iterable, List, Tuple

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
    pre_set = set(pre_visible)
    post_set = set(post_visible)

    # Return now_visible as a list of objects with at least the 'question' field
    # to satisfy Epic E contract expectations. Answer is optional and omitted
    # when not readily available without extra I/O.
    _new_visible_ids = sorted(list(post_set - pre_set))
    now_visible = [{"question": qid} for qid in _new_visible_ids]
    now_hidden = sorted(list(pre_set - post_set))

    suppressed_answers: List[str] = []
    for qid in now_hidden:
        if has_answer(qid):
            suppressed_answers.append(qid)

    return now_visible, now_hidden, suppressed_answers
