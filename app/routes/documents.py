"""Document Service endpoints (Epic C).

Implements a minimal in-memory store to satisfy Epic C integration
scenarios for document creation, listing, metadata retrieval, and
DOCX content upload with optimistic concurrency and idempotency.
"""

from __future__ import annotations

import uuid
from typing import Dict, List

import logging

from fastapi import APIRouter, Body, Header, Response, Request
from fastapi.responses import JSONResponse
from app.logic.etag import doc_etag, compute_document_list_etag
from app.logic.docx_validation import is_valid_docx
from app.logic.idempotency import get_idem_map, record_idem
from app.logic.repository_documents import (
    list_documents as repo_list_documents,
    get_document as repo_get_document,
    order_number_exists as repo_order_number_exists,
    create_document as repo_create_document,
    update_title as repo_update_title,
    delete_document as repo_delete_document,
    resequence_contiguous as repo_resequence,
    apply_ordering as repo_apply_ordering,
)
from app.logic.repository_document_blobs import (
    get_blob as repo_get_blob,
    set_blob as repo_set_blob,
    delete_blob as repo_delete_blob,
)
from app.logic.inmemory_state import (
    DOCUMENTS_STORE,
    DOCUMENT_BLOBS_STORE,
    IDEMPOTENCY_STORE,
    PLACEHOLDERS_BY_ID,
    PLACEHOLDERS_BY_QUESTION,
)


router = APIRouter()
logger = logging.getLogger(__name__)


def _not_implemented(detail: str = "") -> JSONResponse:
    payload = {"title": "Not implemented", "status": 501}
    if detail:
        payload["detail"] = detail
    return JSONResponse(payload, status_code=501, media_type="application/problem+json")


# ----------------------
# In-memory ephemeral store (test-only)
# Single source of truth is defined in app.logic.inmemory_state
# ----------------------


@router.post("/documents", summary="Create a document")
def create_document(payload: dict = Body(...)):
    # Validate payload shape
    try:
        title = str(payload.get("title", "")).strip()
        order_number = int(payload.get("order_number"))
    except (TypeError, ValueError):
        return JSONResponse(
            {"title": "Unprocessable Entity", "status": 422, "detail": "Invalid create payload"},
            status_code=422,
            media_type="application/problem+json",
        )
    if not title or order_number < 1:
        return JSONResponse(
            {"title": "Unprocessable Entity", "status": 422, "detail": "Invalid create payload"},
            status_code=422,
            media_type="application/problem+json",
        )
    # Enforce unique order_number in memory via repository helper
    if repo_order_number_exists(order_number, store=DOCUMENTS_STORE):  # type: ignore[arg-type]
            return JSONResponse(
                {
                    "title": "Conflict",
                    "status": 409,
                    "detail": "order_number already exists",
                    "code": "PRE_ORDER_NUMBER_DUPLICATE",
                },
                status_code=409,
                media_type="application/problem+json",
            )
    # Create document with server-assigned UUIDv4 and version=1
    # Delegate creation to repository (inject in-memory store)
    doc = repo_create_document(title, order_number, store=DOCUMENTS_STORE)  # type: ignore[arg-type]
    document_id = doc["document_id"]
    # Return 201 with DocumentResponse envelope
    return JSONResponse({"document": doc}, status_code=201)


@router.get("/documents/names", summary="List document names")
def get_document_names():
    items = [
        {
            "document_id": doc["document_id"],
            "title": doc["title"],
            "order_number": int(doc["order_number"]),
            "version": int(doc["version"]),
        }
        for doc in repo_list_documents(store=DOCUMENTS_STORE)  # type: ignore[arg-type]
    ]
    body = {"list": items, "list_etag": compute_document_list_etag(items)}
    resp = JSONResponse(body, status_code=200)
    # Align header ETag with body.list_etag for clients capturing either source
    resp.headers["ETag"] = body["list_etag"]
    return resp


@router.get("/documents/{document_id}", summary="Get document metadata")
def get_document(document_id: str, response: Response):
    doc = repo_get_document(document_id, store=DOCUMENTS_STORE)  # type: ignore[arg-type]
    if not doc:
        return JSONResponse(
            {"title": "Not Found", "status": 404, "detail": "document not found"},
            status_code=404,
            media_type="application/problem+json",
        )
    # Attach ETag to the actual response object being returned
    etag = doc_etag(int(doc["version"]))
    resp = JSONResponse({"document": doc}, status_code=200)
    resp.headers["ETag"] = etag
    return resp


@router.patch("/documents/{document_id}", summary="Patch document (skeleton)")
def patch_document(document_id: str, body: dict = Body(...)):
    # Validate existence
    doc = repo_get_document(document_id, store=DOCUMENTS_STORE)  # type: ignore[arg-type]
    if not doc:
        return JSONResponse(
            {"title": "Not Found", "status": 404, "detail": "document not found"},
            status_code=404,
            media_type="application/problem+json",
        )
    # Validate payload
    if not isinstance(body, dict):
        return JSONResponse(
            {"title": "Unprocessable Entity", "status": 422, "detail": "Invalid patch payload"},
            status_code=422,
            media_type="application/problem+json",
        )
    title = body.get("title")
    if title is not None:
        try:
            title_str = str(title).strip()
        except (TypeError, ValueError):
            title_str = ""
        if not title_str:
            return JSONResponse(
                {"title": "Unprocessable Entity", "status": 422, "detail": "Invalid patch payload"},
                status_code=422,
                media_type="application/problem+json",
            )
        # Update only the title; keep order_number and version unchanged
        repo_update_title(document_id, title_str, store=DOCUMENTS_STORE)  # type: ignore[arg-type]
    # Prepare response with current ETag
    current_version = int(doc["version"])
    etag = doc_etag(current_version)
    resp = JSONResponse({"document": doc}, status_code=200)
    resp.headers["ETag"] = etag
    return resp


@router.delete("/documents/{document_id}", summary="Delete document")
def delete_document(document_id: str):
    # Basic validation for path parameter
    try:
        uuid.UUID(str(document_id))
    except (ValueError, TypeError):
        return JSONResponse(
            {"title": "Unprocessable Entity", "status": 422, "detail": "invalid document_id"},
            status_code=422,
            media_type="application/problem+json",
        )

    # Lookup and delete document
    doc = repo_get_document(document_id, store=DOCUMENTS_STORE)  # type: ignore[arg-type]
    if not doc:
        return JSONResponse(
            {"title": "Not Found", "status": 404, "detail": "document not found"},
            status_code=404,
            media_type="application/problem+json",
        )

    # Remove document and associated state (blob + idempotency keys)
    repo_delete_document(document_id, store=DOCUMENTS_STORE)  # type: ignore[arg-type]
    repo_delete_blob(document_id, store=DOCUMENT_BLOBS_STORE)  # type: ignore[arg-type]
    IDEMPOTENCY_STORE.pop(document_id, None)

    # Resequence remaining documents to contiguous 1..N preserving current relative order
    repo_resequence(store=DOCUMENTS_STORE)  # type: ignore[arg-type]

    # 204 No Content on successful deletion
    return Response(status_code=204)


# ----------------------
# Epic D – Bindings purge (skeleton per Clarke)
# ----------------------


@router.post(
    "/documents/{id}/bindings:purge",
    summary="Purge bindings for a document (skeleton)",
    description="returns schemas/PurgeResponse.json",
)
async def post_document_bindings_purge(id: str, request: Request) -> Response:  # noqa: D401
    """Remove placeholders associated with the given document id.

    Behaviour per Clarke:
    - 404 if unknown id (unless id == 'doc-noop', which returns zeros)
    - Return counters {deleted_placeholders:int, updated_questions:int}
    """
    # Special-case no-op id that returns zeros with 200
    if id == "doc-noop":
        return JSONResponse({"deleted_placeholders": 0, "updated_questions": 0}, status_code=200)

    # Determine whether document id is known (by metadata or by any placeholder referencing it)
    doc_known = id in DOCUMENTS_STORE
    if not doc_known:
        for rec in PLACEHOLDERS_BY_ID.values():
            if rec.get("document_id") == id:
                doc_known = True
                break
    if not doc_known:
        return JSONResponse(
            {"title": "not found", "status": 404, "detail": "not found"},
            status_code=404,
            media_type="application/problem+json",
        )

    # Purge placeholders tied to this document id
    deleted = 0
    touched_questions: set[str] = set()
    # Remove from by-id map and gather affected question_ids
    to_delete = [ph_id for ph_id, rec in PLACEHOLDERS_BY_ID.items() if rec.get("document_id") == id]
    for ph_id in to_delete:
        rec = PLACEHOLDERS_BY_ID.pop(ph_id, None) or {}
        qid = str(rec.get("question_id", ""))
        if qid:
            touched_questions.add(qid)
        deleted += 1
    # Remove from per-question lists
    for qid, items in list(PLACEHOLDERS_BY_QUESTION.items()):
        kept = [r for r in (items or []) if r.get("document_id") != id]
        if len(kept) != len(items or []):
            touched_questions.add(str(qid))
        PLACEHOLDERS_BY_QUESTION[qid] = kept

    return JSONResponse(
        {"deleted_placeholders": int(deleted), "updated_questions": int(len(touched_questions))},
        status_code=200,
    )


@router.put(
    "/documents/{document_id}/content",
    summary="Upload DOCX content",
)
async def put_document_content(
    document_id: str,
    request: Request,
    response: Response,  # injected by FastAPI
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    if_match: str | None = Header(default=None, alias="If-Match"),
    content_type: str | None = Header(default=None, alias="Content-Type"),
):
    # Validate existence
    doc = repo_get_document(document_id, store=DOCUMENTS_STORE)  # type: ignore[arg-type]
    if not doc:
        return JSONResponse(
            {
                "title": "Not Found",
                "status": 404,
                "detail": "document not found",
                "code": "PRE_DOCUMENT_NOT_FOUND",
            },
            status_code=404,
            media_type="application/problem+json",
        )
    # Enforce DOCX MIME before any validation or body read
    expected_mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    if not isinstance(content_type, str) or not content_type.startswith(expected_mime):
        return JSONResponse(
            {
                "title": "Unsupported Media Type",
                "status": 415,
                "detail": "Content-Type must be application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "code": "PRE_CONTENT_TYPE_MISMATCH",
            },
            status_code=415,
            media_type="application/problem+json",
        )
    # Idempotency-first: if the same key is provided and recorded, return the
    # previously computed success immediately (ignore potentially stale If-Match)
    idem_map = get_idem_map(IDEMPOTENCY_STORE, document_id)
    if idempotency_key and idempotency_key in idem_map:
        new_version = int(idem_map[idempotency_key])
        response.headers["ETag"] = doc_etag(new_version)
        return JSONResponse(
            {"content_result": {"document_id": document_id, "version": new_version}},
            status_code=200,
        )

    current_version = int(doc["version"])
    current_etag = doc_etag(current_version)
    # Preconditions: If-Match must be present and match current ETag
    if not if_match or not str(if_match).strip():
        return JSONResponse(
            {
                "title": "Precondition Required",
                "status": 428,
                "detail": "If-Match header is required",
                "code": "PRE_IF_MATCH_MISSING_DOCUMENT",
            },
            status_code=428,
            media_type="application/problem+json",
        )
    if str(if_match).strip() != current_etag:
        return JSONResponse(
            {
                "title": "Precondition Failed",
                "status": 412,
                "detail": "ETag mismatch",
                "code": "RUN_DOC_ETAG_MISMATCH",
            },
            status_code=412,
            media_type="application/problem+json",
        )
    # Read raw body only after preconditions pass
    content = await request.body()
    # Validate DOCX-like content via helper
    if not is_valid_docx(content):
        return JSONResponse(
            {
                "title": "Unprocessable Entity",
                "status": 422,
                "detail": "Invalid or non-DOCX content",
                "code": "RUN_UPLOAD_VALIDATION_FAILED",
            },
            status_code=422,
            media_type="application/problem+json",
        )
    # First-time upload (or no idempotency key provided): increment version
    new_version = current_version + 1
    doc["version"] = new_version
    # Persist the uploaded bytes as the current content for GET
    repo_set_blob(document_id, bytes(content), store=DOCUMENT_BLOBS_STORE)  # type: ignore[arg-type]
    if idempotency_key:
        record_idem(idem_map, idempotency_key, new_version)
    response.headers["ETag"] = doc_etag(new_version)
    return JSONResponse({"content_result": {"document_id": document_id, "version": new_version}}, status_code=200)


@router.get(
    "/documents/{document_id}/content",
    summary="Download DOCX content",
)
def get_document_content(document_id: str):
    # Validate document exists and content has been uploaded
    if document_id not in DOCUMENTS_STORE:
        return JSONResponse(
            {"title": "Not Found", "status": 404, "detail": "document not found"},
            status_code=404,
            media_type="application/problem+json",
        )
    blob = repo_get_blob(document_id, store=DOCUMENT_BLOBS_STORE)  # type: ignore[arg-type]
    if not isinstance(blob, (bytes, bytearray)) or len(blob) == 0:
        return JSONResponse(
            {"title": "Not Found", "status": 404, "detail": "document not found"},
            status_code=404,
            media_type="application/problem+json",
        )
    return Response(
        content=bytes(blob),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        status_code=200,
    )


@router.put("/documents/order", summary="Reorder documents")
def put_documents_order(
    body: dict = Body(...),
    if_match: str | None = Header(default=None, alias="If-Match"),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
):
    # Validate If-Match header against current list_etag
    current = compute_document_list_etag(list(DOCUMENTS_STORE.values()))
    # Entry debug log for troubleshooting reorder failures
    logger.info(
        "reorder.entry if_match=%r current_list_etag=%s request_id=%s",
        if_match,
        current,
        request_id,
    )
    # Normalize If-Match to accept quoted and weak validators, e.g. W/"token" or "token"
    normalized = None
    if isinstance(if_match, str):
        candidate = if_match.strip()
        # Drop optional weak validator prefix
        if candidate.startswith("W/"):
            candidate = candidate[2:].lstrip()
        # Strip surrounding quotes if present
        if len(candidate) >= 2 and candidate[0] == '"' and candidate[-1] == '"':
            candidate = candidate[1:-1]
        normalized = candidate
    if not normalized or normalized != current:
        # Build problem payload with diagnostic fields for observability
        problem = {
            "title": "Precondition Failed",
            "status": 412,
            "detail": "list ETag mismatch",
            "code": "RUN_LIST_ETAG_MISMATCH",
            # Instrumentation: include current list ETag and normalized If-Match
            "current_list_etag": current,
            "received_if_match": normalized,
        }
        resp = JSONResponse(
            problem,
            status_code=412,
            media_type="application/problem+json",
        )
        # Expose current list ETag and normalized If-Match in headers
        resp.headers["ETag"] = current
        resp.headers["X-List-ETag"] = current
        if normalized is not None:
            resp.headers["X-If-Match-Normalized"] = normalized
        # Structured log adjacent to 412 response for observability
        logger.info(
            "reorder.precondition_failed_412 if_match=%r current_list_etag=%s request_id=%s",
            if_match,
            current,
            request_id,
        )
        return resp
    # Validate payload structure
    if not isinstance(body, dict):
        return JSONResponse(
            {"title": "Unprocessable Entity", "status": 422, "detail": "Invalid reorder payload"},
            status_code=422,
            media_type="application/problem+json",
        )
    items = body.get("items")
    if not isinstance(items, list) or not items:
        return JSONResponse(
            {"title": "Unprocessable Entity", "status": 422, "detail": "Invalid reorder payload"},
            status_code=422,
            media_type="application/problem+json",
        )
    # Build proposed ordering and validate IDs and sequence
    try:
        proposed: Dict[str, int] = {str(i["document_id"]): int(i["order_number"]) for i in items}
    except (TypeError, ValueError, KeyError):
        return JSONResponse(
            {"title": "Unprocessable Entity", "status": 422, "detail": "Invalid reorder payload"},
            status_code=422,
            media_type="application/problem+json",
        )
    # Ensure all provided IDs exist
    for document_id_key in proposed.keys():
        if document_id_key not in DOCUMENTS_STORE:
            return JSONResponse(
                {"title": "Unprocessable Entity", "status": 422, "detail": "Invalid reorder payload"},
                status_code=422,
                media_type="application/problem+json",
            )
    # Ensure order numbers are 1..N contiguous without gaps
    seq = sorted(set(proposed.values()))
    if seq != list(range(1, len(seq) + 1)):
        return JSONResponse(
            {"title": "Unprocessable Entity", "status": 422, "detail": "Invalid reorder payload"},
            status_code=422,
            media_type="application/problem+json",
        )
    # Apply ordering atomically
    repo_apply_ordering(proposed, store=DOCUMENTS_STORE)  # type: ignore[arg-type]
    # Prepare response
    items_out = [
        {
            "document_id": doc["document_id"],
            "title": doc["title"],
            "order_number": int(doc["order_number"]),
            "version": int(doc["version"]),
        }
        for doc in repo_list_documents(store=DOCUMENTS_STORE)  # type: ignore[arg-type]
    ]
    return JSONResponse({"list": items_out, "list_etag": compute_document_list_etag(items_out)}, status_code=200)


__all__ = [
    "router",
    "create_document",
    "get_document_names",
    "get_document",
    "patch_document",
    "delete_document",
    "put_document_content",
    "get_document_content",
    "put_documents_order",
]
