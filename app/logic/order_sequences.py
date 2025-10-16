"""Authoring order reindexing helpers (Epic G).

Provides backend-authoritative, contiguous 1-based reindexing for
screen_order and question_order when inserting, reordering, or moving
resources within/between containers.
"""

from __future__ import annotations

from typing import Dict, Tuple, Optional

from sqlalchemy import text as sql_text

from app.db.base import get_engine


def reindex_screens(questionnaire_id: str, proposed_position: Optional[int]) -> int:
    """Shift existing screen orders and return the final order for a new/relocated screen.

    - When ``proposed_position`` is None, append to the end and return next order.
    - When provided and <= current length+1, shift existing rows at/after the
      target position up by 1 and return that position.
    - When provided and > length+1, treat as append.

    Returns the final order value that should be assigned to the new screen.
    """
    eng = get_engine()
    with eng.connect() as conn:
        # Determine current max and count
        row = conn.execute(
            sql_text(
                "SELECT COALESCE(MAX(screen_order), 0), COUNT(*) FROM screens WHERE questionnaire_id = :qid"
            ),
            {"qid": questionnaire_id},
        ).fetchone()
        max_order = int(row[0]) if row and row[0] is not None else 0
        count = int(row[1]) if row and row[1] is not None else 0

        if proposed_position is None or int(proposed_position) <= 0:
            # Append (or caller will handle validation for non-positive separately)
            return max_order + 1

        pos = int(proposed_position)
        if pos > (count + 1):
            # Beyond end -> append
            return max_order + 1

        # Shift existing rows at or after the proposed position
        conn.execute(
            sql_text(
                "UPDATE screens SET screen_order = screen_order + 1 WHERE questionnaire_id = :qid AND screen_order >= :pos"
            ),
            {"qid": questionnaire_id, "pos": pos},
        )
        return pos


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

        # Persist updated orders for existing questions in this screen
        for qid, ord_val in new_orders.items():
            conn.execute(
                sql_text(
                    "UPDATE questionnaire_question SET question_order = :ord WHERE question_id = :qid AND screen_key = :sid"
                ),
                {"ord": int(ord_val), "qid": qid, "sid": screen_id},
            )

        final_order = new_orders.get(str(question_id), len(working) + 1)
        return int(final_order), new_orders

