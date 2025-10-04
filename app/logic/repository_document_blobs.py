"""In-memory repository for document binary content (DOCX)."""

from __future__ import annotations

from typing import Dict, Optional


def get_blob(document_id: str, store: Dict[str, bytes]) -> Optional[bytes]:
    return store.get(document_id)


def set_blob(document_id: str, data: bytes, store: Dict[str, bytes]) -> None:
    store[document_id] = bytes(data)


def delete_blob(document_id: str, store: Dict[str, bytes]) -> None:
    store.pop(document_id, None)
