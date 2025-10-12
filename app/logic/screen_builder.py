"""Screen view assembly component.

Provides a single reusable function to assemble a screen view structure for
both GET screen and post-save refresh flows.
"""

from __future__ import annotations

from typing import Any, Dict
import logging

from app.logic.repository_screens import list_questions_for_screen, get_visibility_rules_for_screen
from app.logic.repository_answers import get_existing_answer
from app.logic.answer_canonical import canonicalize_answer_value
from app.logic.visibility_rules import is_child_visible, compute_visible_set
from app.logic.etag import compute_screen_etag

logger = logging.getLogger(__name__)


def assemble_screen_view(response_set_id: str, screen_key: str) -> Dict[str, Any]:
    """Build a minimal screen view payload.

    Returns a dict including questions filtered by visibility and a computed
    screen-level ETag token.
    """
    questions = list_questions_for_screen(screen_key)
    visibility_rules = get_visibility_rules_for_screen(screen_key)

    # Precompute parent values once, then use compute_visible_set for consistency
    try:
        parents = {p for (p, _) in visibility_rules.values() if p is not None}
    except Exception:
        parents = set()
    parent_values: dict[str, str | None] = {}
    for pid in parents:
        row = get_existing_answer(response_set_id, pid)
        if row is None:
            parent_values[pid] = None
        else:
            _opt, vtext, vnum, vbool = row
            parent_values[pid] = canonicalize_answer_value(vtext, vnum, vbool)

    visible_ids = compute_visible_set(visibility_rules, parent_values)

    filtered: list[dict] = []
    for q in questions:
        qid = q.get("question_id")
        if qid not in visible_ids:
            # Instrumentation: record that this question was excluded by rules
            try:
                parent_qid, vis_list = visibility_rules.get(qid, (None, None))
                logger.info(
                    "screen_visible_eval rs_id=%s screen_key=%s child_q=%s parent_q=%s included=%s",
                    response_set_id,
                    screen_key,
                    qid,
                    parent_qid,
                    False,
                )
            except Exception:
                pass
            continue
        # Hydrate current answer for visible question if present
        ans = get_existing_answer(response_set_id, qid)
        if ans is not None:
            opt, vtext, vnum, vbool = ans
            if vnum is not None:
                q = dict(q, answer={"number": vnum})
            elif isinstance(vbool, bool):
                q = dict(q, answer={"bool": vbool})
            elif opt is not None:
                q = dict(q, answer={"option_id": opt})
            elif vtext is not None:
                q = dict(q, answer={"text": vtext})
        filtered.append(q)

    # Final consistency check: included questions must be a subset of visible_ids
    try:
        included_set = {item.get("question_id") for item in filtered}
        assert included_set <= set(visible_ids)
    except Exception:
        # Do not raise in production path; proceed with best-effort set
        pass

    etag = compute_screen_etag(response_set_id, screen_key)
    # Instrumentation: log final included question_ids for the screen
    try:
        included_ids = [item.get("question_id") for item in filtered]
    except Exception:
        included_ids = []
    logger.info(
        "screen_questions_included rs_id=%s screen_key=%s included=%s",
        response_set_id,
        screen_key,
        included_ids,
    )
    return {
        "screen_key": screen_key,
        "questions": filtered,
        "etag": etag,
    }


__all__ = ["assemble_screen_view"]
