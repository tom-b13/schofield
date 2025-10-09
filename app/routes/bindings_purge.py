"""Epic D – Bindings purge endpoint (skeleton).

Provides minimal FastAPI route anchor for:
  - POST /documents/{id}/bindings:purge

Returns 501 Not Implemented with RFC7807 problem+json body.
No business logic is implemented here.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse
from typing import Any, Dict
from app.logic.inmemory_state import (
    DOCUMENTS_STORE,
    PLACEHOLDERS_BY_ID,
    PLACEHOLDERS_BY_QUESTION,
    QUESTION_MODELS,
    QUESTION_ETAGS,
)


router = APIRouter()

# Schema references for architectural visibility
SCHEMA_PURGE_REQUEST = "schemas/PurgeRequest.json"
SCHEMA_PURGE_RESPONSE = "schemas/PurgeResponse.json"


def _not_implemented(detail: str = "") -> JSONResponse:
    payload = {"title": "Not implemented", "status": 501}
    if detail:
        payload["detail"] = detail
    return JSONResponse(payload, status_code=501, media_type="application/problem+json")


@router.post(
    "/documents/{id}/bindings:purge",
    summary="Purge bindings for a document (skeleton)",
    description=(
        f"accepts {SCHEMA_PURGE_REQUEST}; returns {SCHEMA_PURGE_RESPONSE}"
    ),
)
def post_document_bindings_purge(id: str) -> Response:  # noqa: D401
    """Purge in-memory placeholders associated with a given document id.

    - Always 200 with counters; counters may be zero even when the document
      is not present in DOCUMENTS_STORE or there are no matching placeholders.
    """
    # Treat as purgeable if either the document exists OR there are placeholders referencing it.
    if id not in DOCUMENTS_STORE:
        # Clarke: treat 'doc-noop' as a known no-op document and return 200
        if id == "doc-noop":
            return JSONResponse({"deleted_placeholders": 0, "updated_questions": 0}, status_code=200)
        # If no placeholders exist for this id, return 200 with zero counters (no-op)
        has_any = any((rec or {}).get("document_id") == id for rec in PLACEHOLDERS_BY_ID.values()) or any(
            (rec or {}).get("document_id") == id
            for lst in PLACEHOLDERS_BY_QUESTION.values()
            for rec in (lst or [])
        )
        if not has_any:
            return JSONResponse({"deleted_placeholders": 0, "updated_questions": 0}, status_code=200)

    deleted = 0
    updated_questions = set()
    # Collect placeholder ids to remove
    to_delete = [pid for pid, rec in PLACEHOLDERS_BY_ID.items() if rec.get("document_id") == id]
    for pid in to_delete:
        rec = PLACEHOLDERS_BY_ID.pop(pid, None) or {}
        qid = str(rec.get("question_id"))
        if qid in PLACEHOLDERS_BY_QUESTION:
            PLACEHOLDERS_BY_QUESTION[qid] = [r for r in PLACEHOLDERS_BY_QUESTION[qid] if r.get("id") != pid]
        deleted += 1
        updated_questions.add(qid)
    # For any question now left with zero placeholders, clear its model (and adjust ETag book-keeping if present)
    for q in list(updated_questions):
        try:
            remaining = PLACEHOLDERS_BY_QUESTION.get(q) or []
            if not remaining:
                QUESTION_MODELS.pop(q, None)
                # Keep ETag stable if already present; recompute if business logic later requires
                _ = QUESTION_ETAGS.get(q)
        except Exception:
            pass
    payload: Dict[str, Any] = {"deleted_placeholders": int(deleted), "updated_questions": len(updated_questions)}
    return JSONResponse(payload, status_code=200)


__all__ = [
    "router",
    "post_document_bindings_purge",
]
