"""ETag computation helpers.

Provides reusable functions to compute weak ETags for screen resources
based on latest answer state. Centralizes logic to satisfy DRY per AGENTS.md.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import text as sql_text

from app.db.base import get_engine


def compute_screen_etag(response_set_id: str, screen_key: str) -> str:
    """Compute a weak ETag for a screen within a response set based on latest answers.

    Uses max(answered_at) and row count for the screen's questions to produce a stable token.
    """
    try:
        eng = get_engine()
        with eng.connect() as conn:
            max_row = conn.execute(
                sql_text(
                    """
                    SELECT MAX(answered_at) AS max_ts, COUNT(*) AS cnt
                    FROM response r
                    WHERE r.response_set_id = :rs
                      AND r.question_id IN (
                          SELECT q.question_id FROM questionnaire_question q WHERE q.screen_key = :skey
                      )
                    """
                ),
                {"rs": response_set_id, "skey": screen_key},
            ).mappings().one_or_none()
        max_ts = str((max_row or {}).get("max_ts") or "0")
        cnt = int((max_row or {}).get("cnt") or 0)
        # Include in-memory screen version to stabilize GET/PATCH parity and ensure
        # ETag changes on writes even when DB writes fall back to in-memory.
        try:
            from app.logic.repository_answers import get_screen_version

            version = int(get_screen_version(response_set_id, screen_key))
        except Exception:
            version = 0
        token = f"{response_set_id}:{screen_key}:{max_ts}:{cnt}:v{version}".encode("utf-8")
        digest = hashlib.sha1(token).hexdigest()
        return f'W/"{digest}"'
    except Exception:
        # Fallback: compute from in-memory per-screen version to guarantee stability
        try:
            from app.logic.repository_answers import get_screen_version

            version = int(get_screen_version(response_set_id, screen_key))
        except Exception:
            version = 0
        token = f"{response_set_id}:{screen_key}:v{version}".encode("utf-8")
        digest = hashlib.sha1(token).hexdigest()
        return f'W/"{digest}"'


def doc_etag(version: int) -> str:
    """Return a weak ETag string for a document version.

    Mirrors the route behavior: W/"doc-v{version}".
    """
    return f'W/"doc-v{int(version)}"'


def compute_document_list_etag(docs: list[dict]) -> str:
    """Compute a stable ETag token for the documents list.

    Produces a plain SHA1 hex digest (no quotes, not weak) matching
    the existing behavior in the documents route.
    The token incorporates document_id, title, order_number, and version,
    ordered by order_number ascending.
    """
    if not docs:
        return hashlib.sha1(b"empty").hexdigest()
    parts: list[bytes] = []
    for doc in sorted(docs, key=lambda doc_item: int(doc_item.get("order_number", 0))):
        token = f"{doc['document_id']}|{doc['title']}|{int(doc['order_number'])}|{int(doc['version'])}"
        parts.append(token.encode("utf-8"))
    return hashlib.sha1(b"\n".join(parts)).hexdigest()


def _normalize_etag_token(value: str | None) -> str:
    """Normalize an ETag/If-Match token for comparison.

    - Preserve wildcard '*'
    - Strip weak validator prefix 'W/'
    - Remove surrounding quotes
    - Return empty string for None/blank
    """
    v = (value or "").strip()
    if not v:
        return ""
    if v == "*":
        return v
    if v.startswith("W/"):
        v = v[2:].strip()
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1]
    return v


def compare_etag(current: str | None, if_match: str | None) -> bool:
    """Return True when the provided If-Match matches the current entity tag.

    Comparison applies normalisation rules and supports the '*' wildcard which
    unconditionally matches. Empty/absent If-Match never matches.
    """
    incoming = _normalize_etag_token(if_match)
    if not incoming:
        return False
    if incoming == "*":
        return True
    current_norm = _normalize_etag_token(current)
    return incoming == current_norm
