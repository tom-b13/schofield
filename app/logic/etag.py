"""ETag computation helpers.

Provides reusable functions to compute weak ETags for screen resources
based on latest answer state. Centralizes logic to satisfy DRY per AGENTS.md.
"""

from __future__ import annotations

import hashlib
from sqlalchemy import text as sql_text
import logging

from app.logic.repository_screens import get_visibility_rules_for_screen
from app.db.base import get_engine
from app.logic.repository_answers import get_existing_answer, get_screen_version
from app.logic.answer_canonical import canonicalize_answer_value
from app.logic.visibility_rules import compute_visible_set

# Lock the public API surface for Phase-0 baseline
__all__ = [
    "compute_screen_etag",
    "compute_authoring_screen_etag",
    "compute_authoring_screen_etag_from_order",
    "compute_authoring_question_etag",
    "compute_questionnaire_etag_for_authoring",
    "doc_etag",
    "compute_document_list_etag",
    "compare_etag",
]

logger = logging.getLogger(__name__)
 
def compute_authoring_screen_etag(screen_key: str, title: str, order: int) -> str:
    """Compute weak ETag for an authoring screen.

    Token shape mirrors routes: "{screen_key}|{title}|{order}" -> SHA1 -> W/"…".
    """
    token = f"{screen_key}|{title}|{int(order)}".encode("utf-8")
    return f'W/"{hashlib.sha1(token).hexdigest()}"'


def compute_authoring_screen_etag_from_order(screen_id: str, order: int) -> str:
    """Compute weak ETag for a screen when only id and order are available.

    Token: "{screen_id}|{order}" -> SHA1 -> W/"…".
    Centralizes logic to avoid inline hashing in routes per AGENTS.md DRY rule.
    """
    token = f"{screen_id}|{int(order)}".encode("utf-8")
    return f'W/"{hashlib.sha1(token).hexdigest()}"'


def compute_authoring_question_etag(question_id: str, question_text: str, order: int) -> str:
    """Compute weak ETag for an authoring question.

    Token shape mirrors routes: "{question_id}|{question_text}|{order}" -> SHA1 -> W/"…".
    """
    token = f"{question_id}|{question_text}|{int(order)}".encode("utf-8")
    return f'W/"{hashlib.sha1(token).hexdigest()}"'

def compute_screen_etag(response_set_id: str, screen_key: str) -> str:
    """Compute a weak ETag for a screen within a response set.

    Deterministic across identical state and stable between GET→PATCH precheck.
    Incorporates both a per-(response_set, screen) monotonic version AND a
    stable fingerprint of the currently visible question_id set so that ETag
    changes when visibility changes.
    """
    # Version component (in-memory first for read-your-writes)
    try:
        version = int(get_screen_version(response_set_id, screen_key))
    except Exception:
        logger.error(
            "compute_screen_etag version compute failed response_set_id=%s screen_key=%s",
            response_set_id,
            screen_key,
            exc_info=True,
        )
        version = 0

    # Visibility fingerprint component (rules + parent values -> visible set)
    try:
        rules = get_visibility_rules_for_screen(screen_key)
        # Collect parent ids as strings
        parents = {str(p) for (p, _vis) in rules.values() if p is not None}
        parent_values: dict[str, str | None] = {}
        for pid in parents:
            row = get_existing_answer(response_set_id, pid)
            if row is None:
                parent_values[pid] = None
            else:
                _opt, vtext, vnum, vbool = row
                cv = canonicalize_answer_value(vtext, vnum, vbool)
                parent_values[pid] = (str(cv) if cv is not None else None)
        visible_ids = sorted(str(x) for x in compute_visible_set(rules, parent_values))
        vis_fp = hashlib.sha1("\n".join(visible_ids).encode("utf-8")).hexdigest()
    except Exception:
        logger.error(
            "compute_screen_etag visibility fingerprint failed response_set_id=%s screen_key=%s",
            response_set_id,
            screen_key,
            exc_info=True,
        )
        # Conservative fallback when rules/answers unavailable
        vis_fp = "none"

    token = f"{response_set_id}:{screen_key}:v{version}|vis:{vis_fp}".encode("utf-8")
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


def compute_questionnaire_etag_for_authoring(questionnaire_id: str) -> str:
    """Compute a weak ETag over the questionnaire's authoring state (screens).

    The digest is derived from the ordered set of (screen_key, title, screen_order)
    for all screens within the questionnaire, ordered by screen_order ascending
    and then screen_key for stability. Returns a weak ETag string (W/"<hex>").
    """
    try:
        eng = get_engine()
        with eng.connect() as conn:
            rows = conn.execute(
                # Support schemas with or without screen_order; when absent, coalesce to 0
                # to retain a deterministic token shape.
                # screen_key is used for stability across renames of UUIDs.
                sql_text(
                    """
                    SELECT screen_key, title,
                           COALESCE(screen_order, 0) AS screen_order
                    FROM screen
                    WHERE questionnaire_id = :qid
                    ORDER BY screen_order ASC, screen_key ASC
                    """
                ),
                {"qid": questionnaire_id},
            ).fetchall()
    except Exception:
        logger.error(
            "compute_questionnaire_etag_for_authoring DB read failed qid=%s",
            questionnaire_id,
            exc_info=True,
        )
        rows = []

    if not rows:
        digest = hashlib.sha1(b"empty").hexdigest()
        return f'W/"{digest}"'

    parts: list[bytes] = []
    for r in rows:
        try:
            skey = str(r[0])
            title = str(r[1])
            order_val = int(r[2])
        except Exception:
            skey = str(r[0]) if len(r) > 0 else ""
            title = str(r[1]) if len(r) > 1 else ""
            try:
                order_val = int(r[2]) if len(r) > 2 else 0
            except Exception:
                order_val = 0
        token = f"{skey}|{title}|{order_val}".encode("utf-8")
        parts.append(token)
    digest = hashlib.sha1(b"\n".join(parts)).hexdigest()
    return f'W/"{digest}"'


def _normalize_etag_token(value: str | None) -> str:
    """Phase-0 If-Match/ETag normaliser (single source of truth).

    Semantics aligned with Epic K / Section 7.1.x tests:
    - Accept a raw header value which may contain comma-separated entity-tags.
    - Respect quoting: split on commas only when not inside quotes.
    - Support weak validators (prefix ``W/``) and treat them as equivalent to
      strong validators for comparison by stripping the prefix.
    - Require balanced quotes across the full header; raise ValueError if not.
    - Ignore empty or invalid tokens (including empty quoted tags "").
    - Return the first valid opaque tag lowercased (without quotes or weak
      prefix). Return an empty string when none found.
    - Preserve wildcard '*' as-is (matches-any precondition).
    """
    if value is None:
        return ""

    s = value.strip()
    if not s:
        return ""

    # Wildcard short-circuit (exact token, not within a list context)
    if s == "*":
        return s

    # Split on commas while being quote-aware
    in_quote = False
    buf: list[str] = []
    parts: list[str] = []
    for ch in s:
        if ch == '"':
            in_quote = not in_quote
            buf.append(ch)
        elif ch == ',' and not in_quote:
            parts.append("".join(buf).strip())
            buf.clear()
        else:
            buf.append(ch)

    if in_quote:
        # Unbalanced quotes across the header value → malformed
        raise ValueError("unterminated quoted string in If-Match header")

    parts.append("".join(buf).strip())

    for raw in parts:
        if not raw:
            continue

        t = raw.strip()
        # Drop weak validator prefix if present (case-insensitive)
        if len(t) >= 2 and t[:2].upper() == "W/":
            t = t[2:].lstrip()

        # Expect quoted entity-tag
        if not (len(t) >= 2 and t.startswith('"') and t.endswith('"')):
            # Invalid token shape → ignore
            continue

        inner = t[1:-1]

        # Empty entity-tags are invalid for precondition evaluation
        if inner == "":
            continue

        # Quotes within the opaque tag are invalid per RFC; treat as invalid.
        if '"' in inner:
            continue

        # Canonicalise to lowercase for comparison across weak/strong variants.
        return inner.lower()

    # No valid tokens found
    return ""

# Public alias for shared If-Match/ETag normalisation (architectural single source)
# Clarke: expose a single normaliser across app/ for diagnostics and comparison
normalize_if_match = _normalize_etag_token


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
