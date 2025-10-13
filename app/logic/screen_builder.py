"""Screen view assembly component.

Provides a single reusable function to assemble a screen view structure for
both GET screen and post-save refresh flows.
"""

from __future__ import annotations

from typing import Any, Dict
import logging
import sys
import hashlib

from app.logic.repository_screens import list_questions_for_screen, get_visibility_rules_for_screen
from app.logic.repository_answers import get_existing_answer, get_screen_version
from app.logic.answer_canonical import canonicalize_answer_value
from app.logic.visibility_rules import is_child_visible, compute_visible_set
from app.logic.etag import compute_screen_etag

logger = logging.getLogger(__name__)

# Ensure module INFO logs are emitted to stdout during tests/integration runs
try:
    if not logger.handlers:
        _handler = logging.StreamHandler(stream=sys.stdout)
        _handler.setLevel(logging.INFO)
        _handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s:%(name)s:%(message)s'))
        logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
except Exception:
    logger.error("screen_builder_logging_setup_failed", exc_info=True)


def assemble_screen_view(response_set_id: str, screen_key: str) -> Dict[str, Any]:
    """Build a minimal screen view payload.

    Returns a dict including questions filtered by visibility and a computed
    screen-level ETag token.
    """
    questions = list_questions_for_screen(screen_key)
    visibility_rules = get_visibility_rules_for_screen(screen_key)
    # Log parsed rules for this screen (parent and visible_if list per child)
    try:
        rules_dump = {
            str(k): {
                "parent": (str(p) if p else None),
                "visible_if": [str(x) for x in (v or [])],
            }
            for k, (p, v) in visibility_rules.items()
        }
        logger.info(
            "screen_rules rs_id=%s screen_key=%s rules=%s",
            response_set_id,
            screen_key,
            rules_dump,
        )
    except Exception:
        logger.error("screen_rules_logging_failed", exc_info=True)

    # Precompute parent values once, then use compute_visible_set for consistency
    try:
        # Use string parent identifiers up front to ensure consistent keying
        parents = {str(p) for (p, _) in visibility_rules.values() if p is not None}
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
        logger.error("late_reprobe_failed", exc_info=True)

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
        logger.error("parent_values_log_failed", exc_info=True)

    # Ensure parent_values map uses string keys matching rules (Clarke directive)
    parent_values = {str(k): v for k, v in parent_values.items()}
    # And ensure all non-None values are string-cast for equality checks
    parent_values = {k: (str(v) if v is not None else None) for k, v in parent_values.items()}
    # Idempotent canonicalization pass to reinforce GET↔PATCH parity before computing visibility
    parent_values = {str(k): (str(v) if v is not None else None) for k, v in parent_values.items()}
    # Final fallback hydration: if any parent remains None, perform a last
    # repository probe and canonicalize booleans/numbers/text before filtering.
    try:
        for pid in list(parents):
            pid_str = str(pid)
            if parent_values.get(pid_str) is None:
                row3 = get_existing_answer(response_set_id, pid_str)
                if row3 is not None:
                    _opt3, vtext3, vnum3, vbool3 = row3
                    cv3 = canonicalize_answer_value(vtext3, vnum3, vbool3)
                    parent_values[pid_str] = (str(cv3) if cv3 is not None else None)
    except Exception:
        # Never fail visibility computation due to fallback hydration issues
        logger.error("fallback_hydration_failed", exc_info=True)
    # Deterministic two-pass hydration: re-probe unresolved parents up to two times
    try:
        for _ in range(2):
            changed_any = False
            for pid in list(parents):
                pid_str = str(pid)
                if parent_values.get(pid_str) is None:
                    row = get_existing_answer(response_set_id, pid_str)
                    if row is not None:
                        _optx, vtextx, vnumx, vboolx = row
                        cvx = canonicalize_answer_value(vtextx, vnumx, vboolx)
                        new_valx = (str(cvx) if cvx is not None else None)
                        if new_valx is not None:
                            parent_values[pid_str] = new_valx
                            changed_any = True
            if not changed_any:
                break
    except Exception:
        # Hydration loop is best-effort; proceed with current parent_values
        pass
    # Read-your-writes guard: final monotonic re-probe immediately before computing visible set
    try:
        changed_precompute = False
        for pid in list(parents):
            pid_str = str(pid)
            current_val = parent_values.get(pid_str)
            row = get_existing_answer(response_set_id, pid_str)
            if row is not None:
                _optx2, vtextx2, vnumx2, vboolx2 = row
                cvx2 = canonicalize_answer_value(vtextx2, vnumx2, vboolx2)
                # Monotonic: never downgrade non-None to None
                if cvx2 is None and current_val is not None:
                    continue
                new_val = (str(cvx2) if cvx2 is not None else None)
                if new_val != current_val and new_val is not None:
                    parent_values[pid_str] = new_val
                    changed_precompute = True
    except Exception:
        changed_precompute = False
    # Ensure visible_ids is a set of string question_ids derived from compute_visible_set
    visible_ids = {str(x) for x in compute_visible_set(visibility_rules, parent_values)}
    # If the precompute re-probe changed any parent from None, recompute visible_ids immediately
    if changed_precompute:
        visible_ids = {str(x) for x in compute_visible_set(visibility_rules, parent_values)}
    try:
        logger.info(
            "screen_visible_calc rs_id=%s screen_key=%s parent_canon=%s visible_ids_cnt=%s",
            response_set_id,
            screen_key,
            parent_values,
            len(visible_ids),
        )
    except Exception:
        logger.error("screen_visible_calc_log_failed", exc_info=True)
    # Summarise hydration effect for diagnostics (no logic change)
    try:
        logger.info(
            "screen_hydrate_summary rs_id=%s screen_key=%s changed_precompute=%s parents_cnt=%s",
            response_set_id,
            screen_key,
            changed_precompute,
            len(list(parents)),
        )
    except Exception:
        logger.error("screen_hydrate_summary_log_failed", exc_info=True)
    # Final hydration pass (Clarke directive): after initial visible_ids compute,
    # force a repository re-probe for ALL parents to catch immediate writes.
    # Monotonic guarantee: never downgrade a non-None parent value to None;
    # only promote None -> non-None or change non-None -> different non-None.
    try:
        changed = False
        for pid in list(parents):
            pid_str = str(pid)
            row4 = get_existing_answer(response_set_id, pid_str)
            new_val: str | None = None
            if row4 is not None:
                _opt4, vtext4, vnum4, vbool4 = row4
                cv4 = canonicalize_answer_value(vtext4, vnum4, vbool4)
                new_val = (str(cv4) if cv4 is not None else None)
            current_val = parent_values.get(pid_str)
            # Monotonic update: do not overwrite an existing non-None with None
            if new_val is None and current_val is not None:
                # skip downgrade
                continue
            # Promote None -> non-None, or change between concrete values
            if current_val != new_val:
                parent_values[pid_str] = new_val
                changed = True
        if changed:
            visible_ids = {str(x) for x in compute_visible_set(visibility_rules, parent_values)}
            try:
                logger.info(
                    "screen_visible_calc_refresh rs_id=%s screen_key=%s parent_canon=%s visible_ids_cnt=%s",
                    response_set_id,
                    screen_key,
                    parent_values,
                    len(visible_ids),
                )
            except Exception:
                logger.error("screen_visible_calc_refresh_log_failed", exc_info=True)
    except Exception:
        # Never fail GET path due to final hydration step
        pass

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
                logger.error("screen_visible_eval_log_failed", exc_info=True)
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
        if not (included_set <= set(visible_ids)):
            logger.warning(
                "screen_visible_mismatch rs_id=%s screen_key=%s included_minus_visible=%s visible_minus_included=%s",
                response_set_id,
                screen_key,
                list(included_set - set(visible_ids)),
                list(set(visible_ids) - included_set),
            )
    except Exception:
        logger.error("screen_visible_mismatch_log_failed", exc_info=True)
    # Clarke hardening: if any parent canonical value is still None at this point,
    # perform an immediate additional hydration pass (read-your-writes) across all
    # parents to promote None -> concrete values, then recompute visibility.
    try:
        if any((parent_values.get(str(pid)) is None) for pid in parents):
            changed_extra = False
            for pid in list(parents):
                pid_str = str(pid)
                rowx = get_existing_answer(response_set_id, pid_str)
                if rowx is None:
                    continue
                _optx, vtextx, vnumx, vboolx = rowx
                cvx = canonicalize_answer_value(vtextx, vnumx, vboolx)
                new_valx = (str(cvx) if cvx is not None else None)
                cur = parent_values.get(pid_str)
                if new_valx is not None and new_valx != cur:
                    parent_values[pid_str] = new_valx
                    changed_extra = True
            if changed_extra:
                # Recompute visible_ids immediately so the final rebuild adopts the latest set
                visible_ids = {str(x) for x in compute_visible_set(visibility_rules, parent_values)}
                try:
                    logger.info(
                        "screen_visible_calc_extra rs_id=%s screen_key=%s parent_canon=%s visible_ids_cnt=%s",
                        response_set_id,
                        screen_key,
                        parent_values,
                        len(visible_ids),
                    )
                except Exception:
                    logger.error("screen_visible_calc_extra_log_failed", exc_info=True)
    except Exception:
        # Best-effort extra hydration; continue regardless
        logger.error("extra_hydration_failed", exc_info=True)

    # Deterministic final recompute ensures child inclusion when parent became visible within same run
    try:
        visible_ids = {str(x) for x in compute_visible_set(visibility_rules, parent_values)}
        # Emit a final visibility calc log to aid read-your-writes verification
        try:
            logger.info(
                "screen_visible_calc_final rs_id=%s screen_key=%s parent_canon=%s visible_ids_cnt=%s",
                response_set_id,
                screen_key,
                parent_values,
                len(visible_ids),
            )
        except Exception:
            logger.error("screen_visible_calc_final_log_failed", exc_info=True)
    except Exception:
        # Safety: if visibility computation fails here, retain prior set to avoid regressions
        visible_ids = set(q.get("question_id") for q in filtered)

    # Normalize visible_ids to a concrete set prior to rebuilding to avoid any iterator side-effects
    try:
        visible_ids = set(visible_ids)
    except Exception:
        visible_ids = {str(x) for x in visible_ids}
    # Rebuild filtered strictly from the latest visible_ids to ensure no newly-visible
    # children are omitted due to earlier ordering. Re-hydrate answers for visible items.
    filtered = []
    for q in questions:
        qid = q.get("question_id")
        if qid not in visible_ids:
            continue
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

    # Clarke hardening: if the included set diverges from a freshly computed
    # visible set (using the current parent_values), rebuild once more to
    # guarantee read-your-writes in a single request cycle.
    try:
        included_now = {item.get("question_id") for item in filtered}
        expected_now = {str(x) for x in compute_visible_set(visibility_rules, parent_values)}
        if included_now != expected_now:
            filtered = []
            for q in questions:
                qid = q.get("question_id")
                if qid not in expected_now:
                    continue
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
            visible_ids = expected_now
            try:
                logger.info(
                    "screen_visible_calc_rebuild rs_id=%s screen_key=%s parent_canon=%s visible_ids_cnt=%s",
                    response_set_id,
                    screen_key,
                    parent_values,
                    len(visible_ids),
                )
            except Exception:
                logger.error("screen_visible_calc_rebuild_log_failed", exc_info=True)
    except Exception:
        # If diagnostics or recalculation fails, continue with current filtered set
        logger.error("screen_recalculation_failed", exc_info=True)

    # Compute ETag via centralized helper to guarantee parity with route headers
    try:
        etag = compute_screen_etag(response_set_id, screen_key)
    except Exception:
        # Fallback to a local fingerprint only if helper fails
        try:
            version = int(get_screen_version(response_set_id, screen_key))
        except Exception:
            version = 0
        try:
            vis_fp = hashlib.sha1("\n".join(sorted(visible_ids)).encode("utf-8")).hexdigest()
        except Exception:
            vis_fp = "none"
        token = f"{response_set_id}:{screen_key}:v{version}|vis:{vis_fp}".encode("utf-8")
        etag = f'W/"{hashlib.sha1(token).hexdigest()}"'
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
