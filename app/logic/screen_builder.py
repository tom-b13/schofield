"""Screen view assembly component.

Provides a single reusable function to assemble a screen view structure for
both GET screen and post-save refresh flows.
"""

from __future__ import annotations

from typing import Any, Dict

from app.logic.repository_screens import list_questions_for_screen, get_visibility_rules_for_screen
from app.logic.repository_answers import get_existing_answer
from app.logic.answer_canonical import canonicalize_answer_value
from app.logic.visibility_rules import is_child_visible
from app.logic.etag import compute_screen_etag


def assemble_screen_view(response_set_id: str, screen_key: str) -> Dict[str, Any]:
    """Build a minimal screen view payload.

    Returns a dict including questions filtered by visibility and a computed
    screen-level ETag token.
    """
    questions = list_questions_for_screen(screen_key)
    visibility_rules = get_visibility_rules_for_screen(screen_key)

    filtered: list[dict] = []
    for q in questions:
        qid = q.get("question_id")
        parent_qid, vis_list = visibility_rules.get(qid, (None, None))
        if not parent_qid:
            # Hydrate current answer for base question if present
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
            continue
        parent_ans = get_existing_answer(response_set_id, parent_qid)
        if parent_ans is None:
            continue
        _opt, vtext, vnum, vbool = parent_ans
        canon = canonicalize_answer_value(vtext, vnum, vbool)
        if is_child_visible(canon, vis_list):
            # Hydrate current answer for visible child question if present
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

    etag = compute_screen_etag(response_set_id, screen_key)
    return {
        "screen_key": screen_key,
        "questions": filtered,
        "etag": etag,
    }


__all__ = ["assemble_screen_view"]
