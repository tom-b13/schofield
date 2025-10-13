"""Visibility state helpers.

Encapsulates parent value hydration and ScreenView-derived visible id sets
to keep route handlers orchestration-focused and compliant with AGENTS.md.
"""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Set
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.logic.repository_answers import get_existing_answer
from app.logic.answer_canonical import canonicalize_answer_value


logger = logging.getLogger(__name__)


def hydrate_parent_values(
    response_set_id: str,
    screen_key: str,
    rules: Dict[str, tuple[Optional[str], Iterable[str]]],
) -> Dict[str, Optional[str]]:
    """Hydrate canonical parent values from the repository.

    Returns a mapping of parent question_id -> canonical string (or None).
    Narrowly logs SQL errors and defaults missing values to None.
    """
    parents: Set[str] = {str(p) for (p, _v) in rules.values() if p is not None}
    parent_value_pre: Dict[str, Optional[str]] = {}
    try:
        for parent_id in parents:
            row = get_existing_answer(response_set_id, parent_id)
            if row is None:
                parent_value_pre[parent_id] = None
            else:
                _opt_id, vtext, vnum, vbool = row
                parent_value_pre[parent_id] = canonicalize_answer_value(vtext, vnum, vbool)
    except SQLAlchemyError:
        logger.error(
            "visibility_precompute_failed rs_id=%s screen_key=%s",
            response_set_id,
            screen_key,
            exc_info=True,
        )
        parent_value_pre = {str(pid): None for pid in parents}
    return parent_value_pre


def visible_ids_from_screen_view(screen_view) -> Set[str]:
    """Extract a set of question_ids from a ScreenView-like object.

    Accepts a Pydantic model with a `questions` attribute containing dicts
    with `question_id` keys.
    """
    return {q.get("question_id") for q in (getattr(screen_view, "questions", []) or [])}

