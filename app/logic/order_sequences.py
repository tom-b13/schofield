"""Authoring order reindexing helpers (Epic G).

Provides backend-authoritative, contiguous 1-based reindexing for
``screen_order`` and ``question_order`` when inserting, reordering, or
moving resources within/between containers. These helpers are the single
source of truth for final order values to satisfy Clarke's contracts.
"""

from __future__ import annotations

from typing import Dict, Tuple, Optional
import logging

from sqlalchemy import text as sql_text

from app.db.base import get_engine

logger = logging.getLogger(__name__)


def reindex_screens(questionnaire_id: str, proposed_position: Optional[int]) -> int:
    """Shift existing screen orders and return the final order for a new/relocated screen.

    - When ``proposed_position`` is None, append to the end and return next order.
    - When provided and <= current length+1, shift existing rows at/after the
      target position up by 1 and return that position.
    - When provided and > length+1, treat as append.

    Returns the final order value that should be assigned to the new screen.
    """
    eng = get_engine()
    # Determine current max and count; if the screen_order column is missing or
    # the SELECT fails, use a fresh connection to compute COUNT(*) only.
    max_order = 0
    count = 0
    with eng.connect() as conn:
        try:
            row = conn.execute(
                sql_text(
                    "SELECT COALESCE(MAX(screen_order), 0), COUNT(*) FROM screen WHERE questionnaire_id = :qid"
                ),
                {"qid": questionnaire_id},
            ).fetchone()
            max_order = int(row[0]) if row and row[0] is not None else 0
            count = int(row[1]) if row and row[1] is not None else 0
        except Exception:
            logger.error(
                "reindex_screens initial aggregate failed qid=%s",
                questionnaire_id,
                exc_info=True,
            )
    if count == 0 and max_order == 0:
        # Fresh connection fallback to avoid operating on an aborted connection
        with eng.connect() as conn2:
            row2 = conn2.execute(
                sql_text("SELECT COUNT(*) FROM screen WHERE questionnaire_id = :qid"),
                {"qid": questionnaire_id},
            ).fetchone()
            count = int(row2[0]) if row2 and row2[0] is not None else 0
            max_order = count

        if proposed_position is None or int(proposed_position) <= 0:
            # Append (or caller will handle validation for non-positive separately)
            return max_order + 1

        pos = int(proposed_position)
        if pos > (count + 1):
            # Beyond end -> append
            return max_order + 1

        try:
            with eng.begin() as write_conn:
                write_conn.execute(
                    sql_text(
                        "UPDATE screen SET screen_order = screen_order + 1 WHERE questionnaire_id = :qid AND screen_order >= :pos"
                    ),
                    {"qid": questionnaire_id, "pos": pos},
                )
            return pos
        except Exception:
            logger.error(
                "reindex_screens shift failed (fresh path) qid=%s pos=%s",
                questionnaire_id,
                pos,
                exc_info=True,
            )
            # If column is missing, skip shifting and just return bounded insert position
            return min(pos, count + 1)
    # Normal path when initial SELECT succeeded
    # Determine final position bounds and ensure 1-based contiguous result
    if proposed_position is None or int(proposed_position) <= 0:
        return max(max_order, count) + 1
    pos = int(proposed_position)
    if pos > (count + 1):
        return max(max_order, count) + 1
    # Shift existing rows at/after pos; if column is absent, skip shifting but still return bounded pos
    try:
        with eng.begin() as write_conn:
            write_conn.execute(
                sql_text(
                    "UPDATE screen SET screen_order = screen_order + 1 WHERE questionnaire_id = :qid AND screen_order >= :pos"
                ),
                {"qid": questionnaire_id, "pos": pos},
            )
    except Exception:
        logger.error(
            "reindex_screens shift failed qid=%s pos=%s",
            questionnaire_id,
            pos,
            exc_info=True,
        )
        return min(pos, count + 1)
    return pos


def reindex_screens_move(
    questionnaire_id: str,
    moved_screen_key: str,
    proposed_position: int,
) -> int:
    """Reindex screens for a questionnaire when an existing screen is moved.

    - Clamps ``proposed_position`` into [1..N] where N is the number of screens.
    - Removes the ``moved_screen_key`` from the current order list if present,
      inserts it at the clamped position, and persists contiguous 1-based
      ``screen_order`` values in a single transaction.
    - Returns the final order for the moved screen.
    """
    eng = get_engine()
    # Clarke instrumentation snapshots
    with eng.connect() as _r0:
        _rows0 = _r0.execute(
            sql_text(
                "SELECT screen_key FROM screen WHERE questionnaire_id = :qid ORDER BY screen_order ASC, screen_key ASC"
            ),
            {"qid": questionnaire_id},
        ).fetchall()
    _before_keys = [str(r[0]) for r in _rows0]

    # Build working list of keys (ordered) and insert the moving key at clamped position
    keys = list(_before_keys)
    if moved_screen_key in keys:
        keys.remove(moved_screen_key)
    # Clamp proposed position into [1..len(keys)+1]
    po = int(proposed_position)
    if po <= 1:
        insert_at = 0
    elif po > len(keys) + 1:
        insert_at = len(keys)
    else:
        insert_at = po - 1
    keys.insert(insert_at, moved_screen_key)

    # Two-phase atomic update to avoid unique collisions on (questionnaire_id, screen_order)
    with eng.begin() as w:
        # Phase 1: temporarily offset all orders to free the unique space
        w.execute(
            sql_text(
                "UPDATE screen SET screen_order = screen_order + 1000 WHERE questionnaire_id = :qid"
            ),
            {"qid": questionnaire_id},
        )
        # Phase 2: write final contiguous 1-based orders derived from computed list
        for idx, sk in enumerate(keys):
            w.execute(
                sql_text(
                    "UPDATE screen SET screen_order = :ord WHERE questionnaire_id = :qid AND screen_key = :skey"
                ),
                {"ord": int(idx + 1), "qid": questionnaire_id, "skey": sk},
            )

    # Read-after-write to ensure persisted value is returned
    with eng.connect() as _rf:
        _row = _rf.execute(
            sql_text(
                "SELECT COALESCE(screen_order, 0) FROM screen WHERE questionnaire_id = :qid AND screen_key = :skey"
            ),
            {"qid": questionnaire_id, "skey": moved_screen_key},
        ).fetchone()
    _final_order = int(_row[0]) if _row and _row[0] is not None else int(keys.index(moved_screen_key) + 1)

    # Post-commit snapshot for logging
    with eng.connect() as _r1:
        _rows1 = _r1.execute(
            sql_text(
                "SELECT screen_key FROM screen WHERE questionnaire_id = :qid ORDER BY screen_order ASC, screen_key ASC"
            ),
            {"qid": questionnaire_id},
        ).fetchall()
    _after_keys = [str(r[0]) for r in _rows1]
    logger.info(
        "reindex_screens_move before keys=%s po=%s insert_at=%s after keys=%s final_order=%s",
        _before_keys,
        po,
        insert_at,
        _after_keys,
        _final_order,
    )
    return _final_order

def reindex_questions(
    screen_id: str,
    question_id: Optional[str],
    proposed_order: Optional[int],
) -> Tuple[int, Dict[str, int]]:
    """Reindex questions within a screen contiguously and return final order for the target.

    If ``question_id`` is provided and already exists in the screen, it will be
    moved to the target order (or end if None), and other questions will be
    shifted accordingly. When ``question_id`` is None, this computes the final
    order for a new question append/insert and updates existing rows to make
    room if a specific position is proposed.

    Returns a tuple: (final_order_for_target, mapping_of_question_id_to_new_order).
    """
    eng = get_engine()
    with eng.begin() as conn:
        rows = conn.execute(
            sql_text(
                "SELECT question_id, COALESCE(question_order, 0) FROM questionnaire_question WHERE screen_key = :sid ORDER BY question_order ASC, question_id ASC"
            ),
            {"sid": screen_id},
        ).fetchall()
        ids = [str(r[0]) for r in rows]
        orders = [int(r[1]) for r in rows]
        current_index = ids.index(str(question_id)) if question_id and str(question_id) in ids else None

        # Build list of question_ids excluding the moving/new one
        working: list[str] = [qid for qid in ids if qid != str(question_id)]
        # Determine insertion index (0-based)
        if proposed_order is None or int(proposed_order) <= 0:
            insert_at = len(working)
        else:
            po = int(proposed_order)
            if po <= 1:
                insert_at = 0
            elif po > len(working) + 1:
                insert_at = len(working)
            else:
                insert_at = po - 1

        # For moves, insert the existing question_id into working list
        if question_id is not None:
            working.insert(insert_at, str(question_id))

        # Compute new contiguous 1-based orders
        new_orders: Dict[str, int] = {qid: i + 1 for i, qid in enumerate(working)}
        # Clarke instrumentation: capture inputs, before/after lists, and mapping stats
        try:
            logger.info(
                "reindex_questions.debug screen_id=%s question_id=%s proposed_order=%s before_ids=%s after_working=%s working_len=%s mapping_count=%s target_planned_order=%s",
                screen_id,
                question_id,
                proposed_order,
                ids,
                working,
                len(working),
                len(new_orders),
                new_orders.get(str(question_id)),
            )
        except Exception:
            logger.error("reindex_questions.debug logging failed", exc_info=True)

        # Two-phase write to avoid unique collisions on (screen_key, question_order)
        # Phase 1: temporarily offset all existing orders for this screen
        conn.execute(
            sql_text(
                "UPDATE questionnaire_question SET question_order = COALESCE(question_order, 0) + 1000 WHERE screen_key = :sid"
            ),
            {"sid": screen_id},
        )
        # Phase 2: persist final contiguous 1-based orders
        for qid, ord_val in new_orders.items():
            conn.execute(
                sql_text(
                    "UPDATE questionnaire_question SET question_order = :ord WHERE question_id = :qid AND screen_key = :sid"
                ),
                {"ord": int(ord_val), "qid": qid, "sid": screen_id},
            )

        # When creating (question_id is None), the caller will use the returned
        # value as the slot for the new row; for moves we return the mapped order
        final_order = new_orders.get(str(question_id), len(working) + 1)
        return int(final_order), new_orders
