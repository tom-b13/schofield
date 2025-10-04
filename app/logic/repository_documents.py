"""In-memory repository for documents (test/dev only).

Encapsulates CRUD operations for documents using an injectable store to
preserve separation of concerns, improve testability, and avoid hidden
module-level state.
"""

from __future__ import annotations

import uuid
from typing import Dict, List, Optional


def list_documents(store: Dict[str, Dict]) -> List[Dict]:
    docs = list(store.values())
    return sorted(docs, key=lambda doc_item: int(doc_item.get("order_number", 0)))


def get_document(document_id: str, store: Dict[str, Dict]) -> Optional[Dict]:
    return store.get(document_id)


def order_number_exists(order_number: int, store: Dict[str, Dict]) -> bool:
    for doc in store.values():
        if int(doc.get("order_number")) == int(order_number):
            return True
    return False


def create_document(title: str, order_number: int, store: Dict[str, Dict]) -> Dict:
    document_id = str(uuid.uuid4())
    doc = {
        "document_id": document_id,
        "title": str(title),
        "order_number": int(order_number),
        "version": 1,
    }
    store[document_id] = doc
    return doc


def update_title(document_id: str, title: str, store: Dict[str, Dict]) -> Optional[Dict]:
    doc = store.get(document_id)
    if not doc:
        return None
    doc["title"] = str(title)
    return doc


def delete_document(document_id: str, store: Dict[str, Dict]) -> bool:
    existed = document_id in store
    store.pop(document_id, None)
    return existed


def resequence_contiguous(store: Dict[str, Dict]) -> None:
    docs_sorted = list_documents(store)
    for idx, doc in enumerate(docs_sorted, start=1):
        doc["order_number"] = idx


def apply_ordering(proposed: Dict[str, int], store: Dict[str, Dict]) -> None:
    for document_id, order_number in proposed.items():
        store[document_id]["order_number"] = int(order_number)
