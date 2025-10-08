"""Central in-memory state holders for Epic C (test/dev only).

Defines the single source of truth for ephemeral document state used by
routes and repositories during tests and local development. This removes
duplicated globals across modules and supports explicit dependency injection.
"""

from __future__ import annotations

from typing import Dict

# Document metadata store: document_id -> document dict
DOCUMENTS_STORE: Dict[str, Dict] = {}

# Current binary content (DOCX) store: document_id -> bytes
DOCUMENT_BLOBS_STORE: Dict[str, bytes] = {}

# Idempotency tracking per document: document_id -> { idempotency_key -> version }
IDEMPOTENCY_STORE: Dict[str, Dict[str, int]] = {}

# Epic D in-memory state (no DB):
# Placeholder storage and replay of idempotent binds.
PLACEHOLDERS_BY_ID: Dict[str, Dict] = {}
PLACEHOLDERS_BY_QUESTION: Dict[str, list[Dict]] = {}
# Composite-key (Idempotency-Key + payload hash) -> placeholder_id
IDEMPOTENT_BINDS: Dict[str, str] = {}
# Full response replay store: Idempotency-Key -> {body, etag}
IDEMPOTENT_RESULTS: Dict[str, dict] = {}
# Track per-question model (answer_kind) and last ETag for conflict/precondition checks
QUESTION_MODELS: Dict[str, str] = {}
QUESTION_ETAGS: Dict[str, str] = {}

__all__ = [
    "DOCUMENTS_STORE",
    "DOCUMENT_BLOBS_STORE",
    "IDEMPOTENCY_STORE",
    "PLACEHOLDERS_BY_ID",
    "PLACEHOLDERS_BY_QUESTION",
    "IDEMPOTENT_BINDS",
    "IDEMPOTENT_RESULTS",
    "QUESTION_MODELS",
    "QUESTION_ETAGS",
]
