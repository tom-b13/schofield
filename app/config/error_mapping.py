"""Central error mapping for precondition guard (Phase-0).

Single source of truth for mapping precondition outcomes to
problem+json codes and HTTP statuses. Guard modules must import
from here instead of hardcoding strings or numbers.

AC-Ref: 6.1.20; EARS: E8, E9.
"""

from __future__ import annotations

# Missing If-Match on write routes
MISSING = {
    "code": "PRE_IF_MATCH_MISSING",
    "status": 428,
}

# Mismatch on answers routes (optimistic concurrency)
MISMATCH_ANSWERS = {
    "code": "PRE_IF_MATCH_ETAG_MISMATCH",
    "status": 409,
}

# Mismatch on documents routes (optimistic concurrency)
MISMATCH_DOCUMENTS = {
    "code": "PRE_IF_MATCH_ETAG_MISMATCH",
    "status": 412,
}

PRECONDITION_ERROR_MAP = {
    "missing": {"code": "PRE_IF_MATCH_MISSING", "status": 428},
    "invalid_format": {"code": "PRE_IF_MATCH_INVALID_FORMAT", "status": 409},
    "mismatch_answers": {"code": "PRE_IF_MATCH_ETAG_MISMATCH", "status": 409},
    "mismatch_documents": {"code": "PRE_IF_MATCH_ETAG_MISMATCH", "status": 412},
}

__all__ = ["PRECONDITION_ERROR_MAP"]
