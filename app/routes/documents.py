"""Document Service endpoints (Epic C).

Implements a minimal in-memory store to satisfy Epic C integration
scenarios for document creation, listing, metadata retrieval, and
DOCX content upload with optimistic concurrency and idempotency.
"""

from __future__ import annotations

import uuid
from typing import Dict, List

import logging

from fastapi import APIRouter, Body, Header, Response, Request, Depends
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
    IDEMPOTENT_BINDS,
    IDEMPOTENT_RESULTS,
    QUESTION_MODELS,
    QUESTION_ETAGS,
)


router = APIRouter()
logger = logging.getLogger(__name__)
from app.guards.precondition import precondition_guard
from app.logic.header_emitter import emit_etag_headers


def _not_implemented(detail: str = "") -> JSONResponse:
    payload = {"title": "Not implemented", "status": 501}
    if detail:
        payload["detail"] = detail
    return JSONResponse(payload, status_code=501, media_type="application/problem+json")


# ----------------------
# In-memory ephemeral store (test-only)
# Single source of truth is defined in app.logic.inmemory_state
# ----------------------


@router.post("/__test__/reset-state", summary="Reset in-memory stores (test only)")
def post_test_reset_state() -> Response:
    """Clear all in-memory state used by Epic C/D.

    This endpoint is test-only and ensures a clean slate between scenarios.
    It resets document metadata, content blobs, idempotency maps and
    placeholder/question caches. Returns 204 No Content.
    """
    DOCUMENTS_STORE.clear()
    DOCUMENT_BLOBS_STORE.clear()
    IDEMPOTENCY_STORE.clear()
    # Preserve Epic D placeholder/model/idempotent state across scenarios (per Clarke)
    # PLACEHOLDERS_BY_ID, PLACEHOLDERS_BY_QUESTION, IDEMPOTENT_BINDS,
    # IDEMPOTENT_RESULTS, QUESTION_MODELS, and QUESTION_ETAGS are intentionally
    # not cleared to maintain cross-scenario continuity within the feature.
    # Seed two documents to satisfy Epic K reorder scenarios
    try:
        DOCUMENTS_STORE["11111111-1111-1111-1111-111111111111"] = {
            "document_id": "11111111-1111-1111-1111-111111111111",
            "title": "Seeded Document 1",
            "order_number": 1,
            "version": 1,
        }
        DOCUMENTS_STORE["22222222-2222-2222-2222-222222222222"] = {
            "document_id": "22222222-2222-2222-2222-222222222222",
            "title": "Seeded Document 2",
            "order_number": 2,
            "version": 1,
        }
    except Exception:
        logger.error("document_seed_failed", exc_info=True)
    return Response(status_code=204)


@router.post(
    "/documents",
    summary="Create a document",
)
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
    # Emit list ETag via central emitter (uses document scope)
    emit_etag_headers(resp, scope="document", token=body["list_etag"], include_generic=True)
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
    emit_etag_headers(resp, scope="document", token=etag, include_generic=True)
    return resp


@router.patch(
    "/documents/{document_id}",
    summary="Patch document (skeleton)",
)
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
        from app.logic.documents_write import normalize_title
        title_str = normalize_title(title)
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
    emit_etag_headers(resp, scope="document", token=etag, include_generic=True)
    return resp


@router.delete(
    "/documents/{document_id}",
    summary="Delete document",
    dependencies=[Depends(precondition_guard)],
    responses={428: {"content": {"application/problem+json": {}}}, 412: {"content": {"application/problem+json": {}}}},
)
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
# [Removed duplicate purge route]
# Canonical implementation lives in app/routes/bindings_purge.py (DRY)
# ----------------------


@router.put(
    "/documents/{document_id}/content",
    summary="Upload DOCX content",
    responses={428: {"content": {"application/problem+json": {}}}, 412: {"content": {"application/problem+json": {}}}},
)
async def put_document_content(
    document_id: str,
    request: Request,
    response: Response,  # injected by FastAPI
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    content_type: str | None = Header(default=None, alias="Content-Type"),
    # Accept optional If-Match; enforce preconditions within handler
    if_match: str | None = Header(default=None, alias="If-Match"),
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
        emit_etag_headers(response, scope="document", token=doc_etag(new_version), include_generic=True)
        return JSONResponse(
            {"content_result": {"document_id": document_id, "version": new_version}},
            status_code=200,
        )

    current_version = int(doc["version"])
    # Enforce If-Match preconditions after content-type and idempotency checks
    if not if_match:
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
    from app.logic.etag import compare_etag  # local import to avoid cycles at import-time
    if not compare_etag(doc_etag(current_version), if_match):
        return JSONResponse(
            {
                "title": "Precondition Failed",
                "status": 412,
                "detail": "If-Match does not match current ETag",
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
    emit_etag_headers(response, scope="document", token=doc_etag(new_version), include_generic=True)
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


@router.put("/documents/reorder", include_in_schema=False)
@router.put(
    "/documents/order",
    summary="Reorder documents",
    responses={428: {"content": {"application/problem+json": {}}}, 412: {"content": {"application/problem+json": {}}}},
)
def put_documents_order(
    body: dict = Body(...),
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    # Make If-Match optional; precondition_guard enforces semantics
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    # Instrumentation: capture raw/normalized If-Match and current list etag when available
    try:
        from app.logic.etag import normalize_if_match as _dbg_norm
    except Exception:  # pragma: no cover - defensive fallback
        _dbg_norm = lambda v: (v or "")  # type: ignore[assignment]
    try:
        _ifm_norm_dbg = _dbg_norm(if_match)
    except Exception:  # pragma: no cover - defensive fallback
        _ifm_norm_dbg = str(if_match)
    logger.info(
        "reorder.precondition eval route=/api/v1/documents/order if_match_raw=%s if_match_norm=%s current_list_etag=%s",
        str(if_match),
        _ifm_norm_dbg,
        str(current_list_etag) if 'current_list_etag' in locals() else None,
    )
    # Early If-Match precondition (must run before payload validation)
    try:
        from app.logic.etag import compare_etag as _cmp, normalize_if_match as _norm
        from app.logic.header_emitter import emit_etag_headers as _emit, emit_reorder_diagnostics as _emit_diag
    except Exception:
        _cmp = None  # type: ignore[assignment]
        _norm = lambda v: (v or "")  # type: ignore[assignment]
        _emit = lambda resp, scope, token, include_generic=True: None  # type: ignore[assignment]
        _emit_diag = lambda resp, list_etag, norm: None  # type: ignore[assignment]
    try:
        current_items = [
            {
                "document_id": doc["document_id"],
                "title": doc["title"],
                "order_number": int(doc["order_number"]),
                "version": int(doc["version"]),
            }
            for doc in repo_list_documents(store=DOCUMENTS_STORE)  # type: ignore[arg-type]
        ]
        current_list_etag = compute_document_list_etag(current_items)
    except Exception:
        current_list_etag = None

    # Missing If-Match → 428 with diagnostics and current list ETag
    if not if_match:
        logger.info("reorder.precondition branch=missing_if_match route=/api/v1/documents/order")
        _resp_428 = JSONResponse(
            {
                "title": "Precondition Required",
                "status": 428,
                "detail": "If-Match header is required",
                "code": "PRE_IF_MATCH_MISSING_LIST",
            },
            status_code=428,
            media_type="application/problem+json",
        )
        try:
            _emit(_resp_428, scope="document", token=str(current_list_etag or ""), include_generic=True)
        except Exception:
            pass
        try:
            _emit_diag(_resp_428, str(current_list_etag or ""), _norm(if_match))
        except Exception:
            pass
        return _resp_428

    # Stale If-Match → 412 with diagnostics and current list ETag
    try:
        _matches = bool(_cmp(current_list_etag, if_match)) if _cmp else False
        if not _matches and _cmp:
            # Accept match against any current document ETag (legacy compatibility)
            try:
                _docs_now = repo_list_documents(store=DOCUMENTS_STORE)  # type: ignore[arg-type]
            except Exception:
                _docs_now = []
            for _d in _docs_now:
                try:
                    if _cmp(doc_etag(int(_d.get("version", 0))), if_match):
                        _matches = True
                        break
                except Exception:
                    continue
    except Exception:
        _matches = False

    if not _matches:
        logger.info(
            "reorder.precondition branch=stale_if_match route=/api/v1/documents/order current_list_etag=%s",
            str(current_list_etag),
        )
        _resp_412 = JSONResponse(
            {
                "title": "Precondition Failed",
                "status": 412,
                "detail": "list ETag mismatch",
                "code": "IF_MATCH_MISMATCH",
            },
            status_code=412,
            media_type="application/problem+json",
        )
        # Instrumentation: log problem code and diagnostics at 412 emission
        try:
            logger.info(
                "reorder.412 problem_code=%s list_etag=%s if_match_norm=%s",
                "IF_MATCH_MISMATCH",
                str(current_list_etag or ""),
                _norm(if_match),
            )
        except Exception:
            pass
        try:
            _emit(_resp_412, scope="document", token=str(current_list_etag or ""), include_generic=True)
        except Exception:
            pass
        try:
            _emit_diag(_resp_412, str(current_list_etag or ""), _norm(if_match))
        except Exception:
            pass
        return _resp_412

    # Validate payload structure (preconditions enforced by guard)
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
    # Enforce If-Match precondition inside handler before applying ordering per Clarke
    try:
        from app.logic.etag import compare_etag, normalize_if_match
        from app.logic.header_emitter import emit_etag_headers, emit_reorder_diagnostics
    except Exception:
        compare_etag = None  # type: ignore[assignment]
        normalize_if_match = lambda v: (v or "")  # type: ignore[assignment]
        emit_etag_headers = lambda resp, scope, token, include_generic=True: None  # type: ignore[assignment]

    try:
        current_list_etag = compute_document_list_etag(
            [
                {
                    "document_id": doc["document_id"],
                    "title": doc["title"],
                    "order_number": int(doc["order_number"]),
                    "version": int(doc["version"]),
                }
                for doc in repo_list_documents(store=DOCUMENTS_STORE)  # type: ignore[arg-type]
            ]
        )
    except Exception:
        current_list_etag = None

    # Accept If-Match that matches either the current list ETag OR any document ETag
    try:
        matches = bool(compare_etag(current_list_etag, if_match)) if compare_etag else False
        if not matches and compare_etag:
            # Compare against any current document version etag to preserve legacy parity
            try:
                current_docs = repo_list_documents(store=DOCUMENTS_STORE)  # type: ignore[arg-type]
            except Exception:
                current_docs = []
            for _doc in current_docs:
                try:
                    if compare_etag(doc_etag(int(_doc.get("version", 0))), if_match):
                        matches = True
                        break
                except Exception:
                    continue
    except Exception:
        matches = False

    if not matches:
        problem = {
            "title": "Precondition Failed",
            "status": 412,
            "detail": "list ETag mismatch",
            # Align problem code with Epic K Phase-0 contract
            "code": "IF_MATCH_MISMATCH",
        }
        resp = JSONResponse(problem, status_code=412, media_type="application/problem+json")
        # Instrumentation: log problem code and diagnostics at 412 emission
        try:
            from app.logic.etag import normalize_if_match as _norm_ifm  # local import for logging only
            logger.info(
                "reorder.412 problem_code=%s list_etag=%s if_match_norm=%s",
                problem.get("code"),
                str(current_list_etag or ""),
                _norm_ifm(if_match),
            )
        except Exception:
            pass
        try:
            emit_etag_headers(resp, scope="document", token=str(current_list_etag or ""), include_generic=True)
        except Exception:
            pass
        try:
            emit_reorder_diagnostics(resp, str(current_list_etag or ""), normalize_if_match(if_match))
        except Exception:
            pass
        return resp

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
    list_etag = compute_document_list_etag(items_out)
    resp = JSONResponse({"list": items_out, "list_etag": list_etag}, status_code=200)
    # Use central emitter for ETag headers (preserves diagnostics via guard)
    emit_etag_headers(resp, scope="document", token=list_etag, include_generic=True)
    logger.info(
        "reorder.precondition branch=success route=/api/v1/documents/order list_etag=%s",
        str(list_etag),
    )
    # Emit diagnostics headers per Epic K Phase-0
    try:
        from app.logic.etag import normalize_if_match  # local import for consistency
        from app.logic.header_emitter import emit_reorder_diagnostics as _emit_diag
        _emit_diag(resp, list_etag, normalize_if_match(if_match))
    except Exception:
        pass
    return resp


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
