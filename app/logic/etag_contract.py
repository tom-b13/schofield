"""Shared ETag precondition contract utilities (Phase-0).

Provides normalisation and If-Match enforcement helpers that preserve legacy
token values while enabling deterministic comparison. Intended for use by
routes that must enforce optimistic concurrency preconditions.
"""

from __future__ import annotations

from typing import Tuple
import logging

from app.logic.etag import compare_etag
from app.logic.etag_normalizer import normalise_if_match

logger = logging.getLogger(__name__)


def enforce_if_match(if_match_header: str | None, current_etag: str) -> tuple[bool, int, dict]:
    """Enforce If-Match against the provided current_etag.

    Returns a tuple: (ok, status_code, problem_json). On success, ok=True and
    status_code is 200 with an empty problem object. On failure, ok=False and
    status_code is 428 (missing) or 409 (mismatch) with a problem+json body
    describing the error.
    """
    # Debug: log normalized header and current etag at entry
    try:
        _norm = normalise_if_match(if_match_header)
    except Exception:  # pragma: no cover
        logger.error("etag_normalise_failed_entry", exc_info=True)
        _norm = str(if_match_header)
    try:
        _current = str(current_etag)
    except Exception:  # pragma: no cover
        logger.error("etag_current_str_cast_failed", exc_info=True)
        _current = None  # type: ignore[assignment]
    logger.info(
        "etag.enforce route=%s matched=%s if_match_norm=%s current=%s",
        None,
        locals().get("matched", None),
        _norm,
        _current,
    )

    # Missing header -> 428 Precondition Required
    if not if_match_header or not str(if_match_header).strip():
        # 428 Precondition Required with explicit problem code per Epic K
        problem = {
            "title": "Precondition Required",
            "status": 428,
            "detail": "If-Match header is required for this operation",
            "code": "PRE_IF_MATCH_MISSING",
        }
        return False, 428, problem

    # Compare using public comparator which applies canonical normalisation
    try:
        matched = compare_etag(current_etag, if_match_header)
    except Exception:
        # Log comparison failures as errors before treating as mismatch
        logger.error("etag_compare_failed", exc_info=True)
        matched = False
    # Debug: log outcome once computed
    try:
        _norm2 = normalise_if_match(if_match_header)
    except Exception:  # pragma: no cover
        logger.error("etag_normalise_failed_outcome", exc_info=True)
        _norm2 = str(if_match_header)
    logger.info(
        "etag.enforce route=%s matched=%s if_match_norm=%s current=%s",
        None,
        bool(matched),
        _norm2,
        str(current_etag),
    )

    if not matched:
        # 409 Conflict semantics for autosave answers per Clarke contract
        problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "If-Match does not match current ETag",
            "code": "PRE_IF_MATCH_ETAG_MISMATCH",
        }
        return False, 409, problem

    return True, 200, {}


__all__ = ["enforce_if_match"]
