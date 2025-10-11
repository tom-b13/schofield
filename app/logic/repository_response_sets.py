"""Response set data access helpers.

Encapsulates simple existence checks to keep route handlers free of inline SQL.
"""

from __future__ import annotations

from sqlalchemy import text as sql_text

from app.db.base import get_engine

# In-memory registry for skeleton mode to recognise created ids without DB
_INMEM_RS_REGISTRY: set[str] = set()


def register_response_set_id(response_set_id: str) -> None:
    """Register a response_set_id in-memory for existence checks.

    Used by skeleton create endpoint so GET screen can succeed without DB.
    """
    if response_set_id:
        _INMEM_RS_REGISTRY.add(str(response_set_id))


def unregister_response_set_id(response_set_id: str) -> None:
    """Remove a response_set_id from the in-memory registry."""
    try:
        _INMEM_RS_REGISTRY.discard(str(response_set_id))
    except Exception:
        # Best-effort in skeleton mode
        pass


def response_set_exists(response_set_id: str) -> bool:
    """Return True if a response_set with the given id exists.

    First consults an in-memory registry seeded by the create/delete
    endpoints; falls back to a DB probe if not present. DB errors are treated
    as absence rather than raising to keep skeleton mode tolerant.
    """
    if str(response_set_id) in _INMEM_RS_REGISTRY:
        return True
    try:
        eng = get_engine()
        with eng.connect() as conn:
            row = conn.execute(
                sql_text("SELECT 1 FROM response_set WHERE response_set_id = :rs LIMIT 1"),
                {"rs": response_set_id},
            ).fetchone()
        return row is not None
    except Exception:
        return False
