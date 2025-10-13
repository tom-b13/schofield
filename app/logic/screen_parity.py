"""Screen parity guard helper.

Provides a best-effort re-assembly/parity check for ScreenView to ensure
GET reflects read-your-writes behavior without broad exception handling in
route handlers.
"""

from __future__ import annotations

from typing import Dict, Optional, Set
import logging

from sqlalchemy.exc import SQLAlchemyError

from app.logic.repository_screens import get_visibility_rules_for_screen
from app.logic.repository_answers import get_existing_answer
from app.logic.answer_canonical import canonicalize_answer_value
from app.logic.visibility_rules import compute_visible_set
from app.logic.screen_builder import assemble_screen_view
from app.models.response_types import ScreenView


logger = logging.getLogger(__name__)


def _parent_canonical_snapshot(response_set_id: str, screen_key: str) -> Dict[str, Optional[str]]:
    """Capture a snapshot of parent canonical values for a screen.

    Returns a mapping of parent question_id -> canonical string (or None).
    Narrowly handles repository failures.
    """
    snapshot: Dict[str, Optional[str]] = {}
    try:
        rules = get_visibility_rules_for_screen(screen_key)
    except SQLAlchemyError:
        logger.error(
            "rules_fetch_failed screen_key=%s",
            screen_key,
            exc_info=True,
        )
        rules = {}
    parents: Set[str] = {str(p) for (p, _v) in rules.values() if p is not None}
    for parent_id in parents:
        try:
            row = get_existing_answer(response_set_id, parent_id)
        except SQLAlchemyError:
            logger.error(
                "parent_probe_failed rs_id=%s parent_id=%s",
                response_set_id,
                parent_id,
                exc_info=True,
            )
            row = None
        if row is None:
            snapshot[parent_id] = None
        else:
            _opt, vtext, vnum, vbool = row
            cv = canonicalize_answer_value(vtext, vnum, vbool)
            snapshot[parent_id] = str(cv) if cv is not None else None
    return snapshot


def ensure_screen_parity(
    response_set_id: str, screen_key: str, screen_view: ScreenView
) -> ScreenView:
    """Attempt to re-assemble the screen once if parent values changed.

    Uses narrow try/except blocks around repository calls and assembly.
    Returns the original screen_view if anything fails.
    """
    try:
        first_ids = {q.get("question_id") for q in (screen_view.questions or [])}
    except Exception:
        # If shape is unexpected, bail out early
        return screen_view

    before_parent = _parent_canonical_snapshot(response_set_id, screen_key)

    # One bounded iteration to converge parity
    try:
        refreshed = ScreenView(**assemble_screen_view(response_set_id, screen_key))
    except SQLAlchemyError:
        logger.error(
            "assemble_screen_view_failed rs_id=%s screen_key=%s",
            response_set_id,
            screen_key,
            exc_info=True,
        )
        return screen_view
    except Exception:
        # Do not fail GET path on unexpected builder errors
        logger.error("assemble_screen_view_unexpected_error", exc_info=True)
        return screen_view

    after_parent = _parent_canonical_snapshot(response_set_id, screen_key)
    ref_ids = {q.get("question_id") for q in (refreshed.questions or [])}
    etag_changed = (refreshed.etag != screen_view.etag)
    parent_changed = (after_parent != before_parent)
    any_parent_none = any(v is None for v in before_parent.values())

    # Also compare against expected visible set derived from rules and parents
    try:
        rules = get_visibility_rules_for_screen(screen_key)
        expected_visible = {str(x) for x in compute_visible_set(rules, after_parent)}
    except SQLAlchemyError:
        logger.error(
            "expected_visible_rules_failed screen_key=%s",
            screen_key,
            exc_info=True,
        )
        expected_visible = set()
    except Exception:
        logger.error("expected_visible_compute_failed", exc_info=True)
        expected_visible = set()

    if (
        (ref_ids != first_ids)
        or etag_changed
        or any_parent_none
        or (not etag_changed and parent_changed)
        or (ref_ids != expected_visible and expected_visible)
    ):
        return refreshed

    return screen_view
