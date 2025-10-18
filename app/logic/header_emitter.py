"""Centralised ETag header emitter.

Provides a single function to set domain-specific ETag headers and the
generic `ETag` header according to scope. Avoids direct header assignment
in route handlers per architectural rule 7.1.5.
"""

from __future__ import annotations

import logging
from fastapi import Response

from app.logic.events import ETAG_EMIT

logger = logging.getLogger(__name__)


SCOPE_TO_HEADER = {
    "screen": "Screen-ETag",
    "question": "Question-ETag",
    "questionnaire": "Questionnaire-ETag",
    "document": "Document-ETag",
}

# Diagnostic header names referenced by architecture and guard diagnostics
# (present for static verification; emission handled by guard/handlers as needed)
X_LIST_ETAG_HEADER = "X-List-ETag"
X_IF_MATCH_NORMALIZED_HEADER = "X-If-Match-Normalized"


def emit_etag_headers(response: Response, scope: str, token: str, include_generic: bool = True) -> None:
    """Set domain and generic ETag headers on the response.

    - `scope`: one of SCOPE_TO_HEADER keys
    - `token`: the entity tag value to set
    - `include_generic`: when True, also set `ETag` alongside the domain header
    """
    header_name = SCOPE_TO_HEADER.get(scope)
    if header_name:
        try:
            response.headers[header_name] = token
        except Exception:
            logger.error("emit_etag_headers_failed_set_domain", exc_info=True)
    if include_generic:
        try:
            response.headers["ETag"] = token
        except Exception:
            logger.error("emit_etag_headers_failed_set_generic", exc_info=True)
    # Ensure Access-Control-Expose-Headers advertises all domain ETag headers
    try:
        existing = response.headers.get("Access-Control-Expose-Headers", "")
        existing_tokens = {t.strip() for t in str(existing).split(",") if t.strip()}
        required = [
            "ETag",
            "Screen-ETag",
            "Question-ETag",
            "Document-ETag",
            "Questionnaire-ETag",
        ]
        merged = []
        seen = set()
        # Preserve stable order using required list, then any existing extras
        for t in required + [t for t in existing_tokens if t not in required]:
            if t and t not in seen:
                merged.append(t)
                seen.add(t)
        response.headers["Access-Control-Expose-Headers"] = ", ".join(merged)
    except Exception:
        logger.error("emit_etag_headers_failed_set_expose_headers", exc_info=True)
    # Structured event log for observability with keyword context
    try:
        logger.info("etag.emit", scope=scope)
    except Exception:
        # Never fail handlers on logging issues
        pass


def emit_reorder_diagnostics(response: Response, list_etag: str, if_match_normalized: str) -> None:
    """Emit reorder diagnostic headers via centralised helper.

    Architectural rule 7.1.23 requires diagnostic headers to be set
    through a shared emitter rather than directly in route handlers.
    """
    try:
        response.headers[X_LIST_ETAG_HEADER] = list_etag
    except Exception:
        logger.error("emit_reorder_diagnostics_failed_list_etag", exc_info=True)
    try:
        response.headers[X_IF_MATCH_NORMALIZED_HEADER] = if_match_normalized
    except Exception:
        logger.error("emit_reorder_diagnostics_failed_if_match", exc_info=True)


__all__ = [
    "emit_etag_headers",
    "emit_reorder_diagnostics",
    "SCOPE_TO_HEADER",
]
