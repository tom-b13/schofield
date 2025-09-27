"""Gating verdict computation.

Computes a basic gating verdict with the shape `{ ok: bool, blocking_items: [] }`.
The actual checklist aggregation is handled by upstream repositories; this module
only performs boolean derivation.
"""

from __future__ import annotations

from typing import Any, Dict, List
import logging
from sqlalchemy import text as sql_text

from app.db.base import get_engine


def evaluate_gating(checklist: Dict[str, Any]) -> Dict[str, Any]:
    """Compute gating verdict using DB-backed mandatory checks.

    A question is considered blocking if it is marked mandatory and the
    response_set has no response row for it.
    """
    rs_id = str(checklist.get("response_set_id") or "")
    logger = logging.getLogger(__name__)
    logger.info("gating_check_start rs_id=%s", rs_id)
    items: List[Dict[str, Any]] = []
    if rs_id:
        eng = get_engine()
        with eng.connect() as conn:
            # Log SQL parameters for traceability
            logger.info("gating_sql_params rs_id=%s", rs_id)
            rows = conn.execute(
                sql_text(
                    """
                    SELECT q.question_id
                    FROM questionnaire_question q
                    WHERE q.mandatory = TRUE
                      AND NOT EXISTS (
                        SELECT 1 FROM response r WHERE r.response_set_id = :rs AND r.question_id = q.question_id
                      )
                    ORDER BY q.question_id ASC
                    """
                ),
                {"rs": rs_id},
            ).fetchall()
            # Optionally capture the number of mandatory questions for coarse diagnostics
            try:
                total_mand = conn.execute(
                    sql_text("SELECT COUNT(*) FROM questionnaire_question WHERE mandatory = TRUE")
                ).fetchone()[0]
            except Exception:
                logger.error("gating_total_mandatory_count_failed rs_id=%s", rs_id, exc_info=True)
                total_mand = None
        # Include a reason for each blocking item to satisfy schema/contract
        missing_ids = [str(row[0]) for row in rows]
        items = [
            {"question_id": mid, "reason": "missing_required_answer"}
            for mid in missing_ids
        ]
    ok = len(items) == 0
    logger.info(
        "gating_verdict rs_id=%s missing=%s total_mandatory=%s",
        rs_id,
        missing_ids,
        total_mand if 'total_mand' in locals() else None,
    )
    return {"ok": ok, "blocking_items": items}
