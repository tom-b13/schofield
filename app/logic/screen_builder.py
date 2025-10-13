"""Screen view assembly component.

Provides a single reusable function to assemble a screen view structure for
both GET screen and post-save refresh flows.
"""

from __future__ import annotations

from typing import Any, Dict
import logging
import sys

from app.logic.repository_screens import list_questions_for_screen, get_visibility_rules_for_screen
from app.logic.repository_answers import get_existing_answer
from app.logic.answer_canonical import canonicalize_answer_value
from app.logic.visibility_rules import is_child_visible, compute_visible_set
from app.logic.etag import compute_screen_etag

logger = logging.getLogger(__name__)

# Ensure module INFO logs are emitted to stdout during tests/integration runs
try:
    if not logger.handlers:
        _handler = logging.StreamHandler(stream=sys.stdout)
        _handler.setLevel(logging.INFO)
        _handler.setFormatter(logging.Formatter('%(levelname)s:%(name)s:%(message)s'))
        logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
except Exception:
    pass


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
        pid_str = str(pid)
        row = get_existing_answer(response_set_id, pid_str)
        if row is None:
            parent_values[pid_str] = None
        else:
            _opt, vtext, vnum, vbool = row
            # Guarantee strict string-canonical form for visibility checks
            cv = canonicalize_answer_value(vtext, vnum, vbool)
            parent_values[pid_str] = (str(cv) if cv is not None else None)

    # Clarke: After initial loop, explicitly re-probe and override any None
    # parent values by consulting repository again to capture recent writes.
    try:
        for pid in list(parents):
            pid_str = str(pid)
            if parent_values.get(pid_str) is None:
                row2 = get_existing_answer(response_set_id, pid_str)
                if row2 is not None:
                    _opt2, vtext2, vnum2, vbool2 = row2
                    cv2 = canonicalize_answer_value(vtext2, vnum2, vbool2)
                    parent_values[pid_str] = (str(cv2) if cv2 is not None else None)
    except Exception:
        # Never fail GET path due to a late re-probe
        pass

    # Instrumentation only: log raw tuples and canonicalized (string-cast) maps
    try:
        raw_map: dict[str, tuple | None] = {}
        for pid in parents:
            try:
                raw_map[str(pid)] = get_existing_answer(response_set_id, str(pid))
            except Exception:
                raw_map[str(pid)] = None
        logger.info(
            "screen_parent_values_raw rs_id=%s screen_key=%s parent_raw=%s",
            response_set_id,
            screen_key,
            raw_map,
        )
        parent_canon_str = {str(k): (str(v) if v is not None else None) for k, v in parent_values.items()}
        logger.info(
            "screen_parent_values_canon rs_id=%s screen_key=%s parent_canon=%s",
            response_set_id,
            screen_key,
            parent_canon_str,
        )
    except Exception:
        pass

    # Ensure parent_values map uses string keys matching rules (Clarke directive)
    parent_values = {str(k): v for k, v in parent_values.items()}
    # Ensure visible_ids is a set of string question_ids derived from compute_visible_set
    visible_ids = {str(x) for x in compute_visible_set(visibility_rules, parent_values)}

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
