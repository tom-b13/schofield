"""ETag computation helpers.

Provides reusable functions to compute weak ETags for screen resources
based on latest answer state. Centralizes logic to satisfy DRY per AGENTS.md.
"""

from __future__ import annotations

import hashlib

from sqlalchemy import text as sql_text

from app.db.base import get_engine


def compute_screen_etag(response_set_id: str, screen_key: str) -> str:
    """Compute a weak ETag for a screen within a response set.

    Deterministic across identical state and stable between GET→PATCH precheck.
    The token is derived strictly from (response_set_id, screen_key, version),
    where `version` is the per-(response_set, screen) monotonic counter bumped
    on every write affecting the screen. This avoids spurious mismatches due to
    clock granularity or row-count races.
    """
    try:
        # Use the in-memory/versioned source of truth first to guarantee parity
        # across GET and subsequent PATCH precondition checks.
        from app.logic.repository_answers import get_screen_version

        version = int(get_screen_version(response_set_id, screen_key))
    except Exception:
        version = 0

    # Only include (response_set_id, screen_key, version) in the hash to keep
    # the ETag deterministic across identical state. Extra DB-derived fields
    # like timestamps or counts are intentionally excluded to prevent drift.
    token = f"{response_set_id}:{screen_key}:v{version}".encode("utf-8")
    digest = hashlib.sha1(token).hexdigest()
    etag = f'W/"{digest}"'
    return etag  # deterministic across identical state


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
    - Strip weak validator prefix 'W/' (case-insensitive)
    - Remove surrounding quotes repeatedly
    - Trim whitespace at each step
    - Compare case-insensitively by lowercasing the token
    - Return empty string for None/blank
    """
    v = (value or "").strip()
    if not v:
        return ""
    # Wildcard must be preserved as-is
    if v == "*":
        return v
    # Strip weak prefixes repeatedly (defensive) and whitespace
    while len(v) >= 2 and v[:2].upper() == "W/":
        v = v[2:].strip()
    # Remove surrounding quotes repeatedly
    while len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1].strip()
    # Case-insensitive hex comparison: normalize to lowercase
    return v.lower()


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
