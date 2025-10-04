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

__all__ = [
    "DOCUMENTS_STORE",
    "DOCUMENT_BLOBS_STORE",
    "IDEMPOTENCY_STORE",
]

