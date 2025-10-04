"""Idempotency helpers for content uploads.

Encapsulates idempotency-key handling to keep route logic slim and
comply with separation of concerns.
"""

from __future__ import annotations

from typing import Dict


def get_idem_map(state: Dict[str, Dict[str, int]], document_id: str) -> Dict[str, int]:
    """Return the idempotency map for a given document from `state`.

    Creates an empty map if one does not exist yet.
    """
    return state.setdefault(document_id, {})


def record_idem(idem_map: Dict[str, int], key: str, version: int) -> None:
    """Record `version` for `key` in the provided idempotency map."""
    if key:
        idem_map[key] = int(version)

