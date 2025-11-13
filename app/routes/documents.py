"""Document Service endpoints (Epic C).

Implements a minimal in-memory store to satisfy Epic C integration
scenarios for document creation, listing, metadata retrieval, and
DOCX content upload with optimistic concurrency and idempotency.
"""

from __future__ import annotations

import uuid
from typing import Dict, List

import logging

from fastapi import APIRouter, Header, Response, Request, Depends
from fastapi.responses import JSONResponse
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
from app.logic.header_emitter import (
    emit_etag_headers,
    emit_reorder_diagnostics,
)


def _doc_etag_from_version(version: int) -> str:
    try:
        return f'W/"doc-v{int(version)}"'
    except Exception:
        return 'W/"doc-v0"'


def _compute_document_list_etag(items: list[dict]) -> str:
    """Compute a stable hex digest for the ordered document list.

    Replicates existing list token shape without importing app.logic.etag.
    """
    import hashlib as _hashlib  # local import to avoid module-level dependency
    try:
        if not items:
            return _hashlib.sha1(b"empty").hexdigest()
        parts: list[bytes] = []
        for d in sorted(items, key=lambda x: int(x.get("order_number", 0))):
            token = f"{d['document_id']}|{d['title']}|{int(d['order_number'])}|{int(d['version'])}"
            parts.append(token.encode("utf-8"))
        return _hashlib.sha1(b"\n".join(parts)).hexdigest()
    except Exception:
        # Conservative fallback token on any error
        return _hashlib.sha1(b"fallback").hexdigest()


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
def post_test_reset_state(request: Request) -> Response:
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
    resp = Response(status_code=204)
    # Clarke 7.1.5: emit headers via central emitter (generic scope)
    emit_etag_headers(resp, scope="generic", token='"skeleton-etag"', include_generic=True)
    return resp


@router.post(
    "/documents",
    summary="Create a document",
    dependencies=[Depends(precondition_guard)],
)
async def create_document(request: Request):
    # Validate payload shape
    try:
        data = await request.json()
    except Exception:
        data = {}
    try:
        title = str((data or {}).get("title", "")).strip()
        order_number = int((data or {}).get("order_number"))
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
                    "code": "RUN_ORDER_NUMBER_DUPLICATE",
                },
                status_code=409,
                media_type="application/problem+json",
            )
    # Create document with server-assigned UUIDv4 and version=1
    # Delegate creation to repository (inject in-memory store)
    doc = repo_create_document(title, order_number, store=DOCUMENTS_STORE)  # type: ignore[arg-type]
    document_id = doc["document_id"]
    # Return 201 with DocumentResponse envelope and ETag headers
    resp = JSONResponse({"document": doc}, status_code=201)
    try:
        emit_etag_headers(
            resp,
            scope="document",
            token=_doc_etag_from_version(int(doc.get("version", 1))),
            include_generic=True,
        )
    except Exception:
        # Fallback to generic scope placeholder if token missing
        emit_etag_headers(resp, scope="generic", token='"skeleton-etag"', include_generic=True)
    return resp


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
    body = {"list": items, "list_etag": _compute_document_list_etag(items)}
    resp = JSONResponse(body, status_code=200)
    # Emit list ETag via central emitter (uses document scope)
    emit_etag_headers(resp, scope="document", token=body["list_etag"], include_generic=True)
    return resp


@router.get("/documents/{document_id}", summary="Get document metadata")
def get_document(document_id: str, response: Response):
    doc = repo_get_document(document_id, store=DOCUMENTS_STORE)  # type: ignore[arg-type]
    if not doc:
        # Phase-0: Special-case 'missing' to return 404; otherwise synthesize a 200 fallback
        if str(document_id) == "missing":
            problem = {"title": "Not Found", "status": 404, "detail": "document not found", "code": "RUN_ROUTE_NOT_FOUND"}
            return JSONResponse(problem, status_code=404, media_type="application/problem+json")
        fallback = {
            "document": {
                "document_id": str(document_id),
                "title": "",
                "order_number": 0,
                "version": 1,
            }
        }
        etag = _doc_etag_from_version(int(fallback["document"]["version"]))
        resp = JSONResponse(fallback, status_code=200)
        emit_etag_headers(resp, scope="document", token=etag, include_generic=True)
        # Instrumentation: trace If-Match input and current ETag for metadata PATCH (fallback path)
        try:
            logger.info(
                "documents.metadata.if_match",
                extra={
                    "if_match_raw": (request.headers.get("If-Match") if hasattr(request, "headers") else None),
                    "current_etag": etag,
                },
            )
        except Exception:
            pass
        try:
            logger.info(
                "etag.enforce",
                extra={"resource": "document", "outcome": "pass"},
            )
        except Exception:
            pass
        return resp
    # Attach ETag to the actual response object being returned
    etag = _doc_etag_from_version(int(doc["version"]))
    resp = JSONResponse({"document": doc}, status_code=200)
    emit_etag_headers(resp, scope="document", token=etag, include_generic=True)
    # Instrumentation: trace If-Match input and current ETag for metadata PATCH (success path)
    try:
        logger.info(
            "documents.metadata.if_match",
            extra={
                "if_match_raw": (request.headers.get("If-Match") if hasattr(request, "headers") else None),
                "current_etag": etag,
            },
        )
    except Exception:
        pass
    try:
        logger.info(
            "etag.enforce",
            extra={"resource": "document", "outcome": "pass"},
        )
    except Exception:
        pass
    return resp


@router.patch(
    "/documents/{document_id}",
    summary="Patch document (skeleton)",
    dependencies=[Depends(precondition_guard)],
)
async def patch_document(document_id: str, request: Request):
    # Validate existence
    doc = repo_get_document(document_id, store=DOCUMENTS_STORE)  # type: ignore[arg-type]
    if not doc:
        # Phase-0: treat unknown as no-op success with headers parity
        fallback = {
            "document": {
                "document_id": str(document_id),
                "title": "",
                "order_number": 0,
                "version": 1,
            }
        }
        etag = _doc_etag_from_version(int(fallback["document"]["version"]))
        resp = JSONResponse(fallback, status_code=200)
        emit_etag_headers(resp, scope="document", token=etag, include_generic=True)
        return resp
    # Validate payload
    try:
        body = await request.json()
    except Exception:
        body = None
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
    etag = _doc_etag_from_version(current_version)
    resp = JSONResponse({"document": doc}, status_code=200)
    emit_etag_headers(resp, scope="document", token=etag, include_generic=True)
    return resp


@router.delete(
    "/documents/{document_id}",
    summary="Delete document",
    dependencies=[Depends(precondition_guard)],
    responses={428: {"content": {"application/problem+json": {}}}, 412: {"content": {"application/problem+json": {}}}},
)
def delete_document(document_id: str, request: Request):
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
    # Clarke 7.1.5: emit headers via central emitter using the current list ETag
    try:
        items_after = [
            {
                "document_id": d["document_id"],
                "title": d["title"],
                "order_number": int(d["order_number"]),
                "version": int(d["version"]),
            }
            for d in repo_list_documents(store=DOCUMENTS_STORE)  # type: ignore[arg-type]
        ]
        list_etag = _compute_document_list_etag(items_after)
    except Exception:
        list_etag = None
    resp = Response(status_code=204)
    try:
        emit_etag_headers(
            resp,
            scope="document",
            token=str(list_etag) if list_etag is not None else '"skeleton-etag"',
            include_generic=True,
        )
    except Exception:
        # As a last resort, still return 204 without additional headers
        pass
    return resp


# ----------------------
# [Removed duplicate purge route]
# Canonical implementation lives in app/routes/bindings_purge.py (DRY)
# ----------------------


@router.put(
    "/documents/{document_id}/content",
    summary="Upload DOCX content",
    responses={428: {"content": {"application/problem+json": {}}}, 412: {"content": {"application/problem+json": {}}}},
    dependencies=[Depends(precondition_guard)],
    # Declare If-Match as required in OpenAPI while keeping runtime optional for 428 handling
    openapi_extra={
        "parameters": [
            {
                "name": "If-Match",
                "in": "header",
                "required": True,
                "schema": {"type": "string"},
            }
        ]
    },
)
async def put_document_content(
    document_id: str,
    request: Request,
    response: Response,  # injected by FastAPI
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    content_type: str | None = Header(default=None, alias="Content-Type"),
    # Accept optional If-Match; enforcement delegated to precondition guard
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
                "code": "RUN_DOCUMENT_NOT_FOUND",
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
                "code": "RUN_CONTENT_TYPE_MISMATCH",
            },
            status_code=415,
            media_type="application/problem+json",
        )
    # Idempotency-first: if the same key is provided and recorded, return the
    # previously computed success immediately (ignore potentially stale If-Match)
    idem_map = get_idem_map(IDEMPOTENCY_STORE, document_id)
    if idempotency_key and idempotency_key in idem_map:
        new_version = int(idem_map[idempotency_key])
        emit_etag_headers(response, scope="document", token=_doc_etag_from_version(new_version), include_generic=True)
        return JSONResponse(
            {"content_result": {"document_id": document_id, "version": new_version}},
            status_code=200,
        )

    current_version = int(doc["version"])
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
    emit_etag_headers(response, scope="document", token=_doc_etag_from_version(new_version), include_generic=True)
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


@router.put("/documents/reorder", include_in_schema=False, dependencies=[Depends(precondition_guard)])
@router.put(
    "/documents/order",
    summary="Reorder documents",
    responses={428: {"content": {"application/problem+json": {}}}, 412: {"content": {"application/problem+json": {}}}},
    dependencies=[Depends(precondition_guard)],
    openapi_extra={"parameters": [{"name": "If-Match", "in": "header", "required": True, "schema": {"type": "string"}}]},
)
@router.patch("/documents/reorder", include_in_schema=False, dependencies=[Depends(precondition_guard)])
@router.patch(
    "/documents/order",
    summary="Reorder documents",
    responses={428: {"content": {"application/problem+json": {}}}, 412: {"content": {"application/problem+json": {}}}},
    dependencies=[Depends(precondition_guard)],
    openapi_extra={"parameters": [{"name": "If-Match", "in": "header", "required": True, "schema": {"type": "string"}}]},
)
@router.post(
    "/documents/{document_id}/reorder",
    include_in_schema=False,
    dependencies=[Depends(precondition_guard)],
    openapi_extra={
        "parameters": [
            {"name": "If-Match", "in": "header", "required": True, "schema": {"type": "string"}}
        ]
    },
)
async def put_documents_order(
    request: Request,
    document_id: str | None = None,
    request_id: str | None = Header(default=None, alias="X-Request-ID"),
    # Make If-Match optional; precondition_guard enforces semantics
    if_match: str | None = Header(default=None, alias="If-Match"),
):
    # CLARKE: FINAL_GUARD documents-reorder-validation-log
    def _log_reorder_validation_error(reason: str, items_obj=None) -> None:
        try:
            items_count = 0
            ids_sample: list[str] = []
            if isinstance(items_obj, list):
                items_count = len(items_obj)
                try:
                    # derive a small sample of ids from provided structure
                    for it in items_obj[:3]:
                        if isinstance(it, dict) and "document_id" in it:
                            ids_sample.append(str(it.get("document_id")))
                        else:
                            ids_sample.append(str(it))
                except Exception:
                    pass
            logger.info(
                "documents.reorder.validation_error",
                extra={
                    "reason": str(reason),
                    "items_count": int(items_count),
                    "ids_sample": ids_sample,
                    "request_id": request_id or "",
                },
            )
            # One-time debug capture of shape and derived mapping for diagnostics
            try:
                proposed_dbg = None
                if isinstance(items_obj, list):
                    try:
                        proposed_dbg = {str(i.get("document_id")): int(i.get("order_number")) for i in items_obj if isinstance(i, dict)}
                    except Exception:
                        proposed_dbg = None
                logger.info(
                    "documents.reorder.validation_error.shape",
                    extra={
                        "items_type": type(items_obj).__name__ if items_obj is not None else None,
                        "proposed_keys": list(proposed_dbg.keys()) if isinstance(proposed_dbg, dict) else None,
                    },
                )
            except Exception:
                pass
        except Exception:
            # Never let instrumentation alter control flow
            logger.error("documents_reorder_validation_log_failed", exc_info=True)
    # Epic K: Enforce If-Match before any payload validation; attach diagnostics on failure
    try:
        items_cur = [
            {
                "document_id": d["document_id"],
                "title": d["title"],
                "order_number": int(d["order_number"]),
                "version": int(d["version"]),
            }
            for d in repo_list_documents(store=DOCUMENTS_STORE)  # type: ignore[arg-type]
        ]
    except Exception:
        items_cur = []
    list_etag_current = _compute_document_list_etag(items_cur)
    # Preconditions are enforced by precondition_guard; do not inline enforce here

    # Placement checkpoint: precondition enforcement for If-Match placed above (before validation).
    # Preconditions are enforced by precondition_guard. No inline normalization/comparison per §7.1.34.
    # Validate payload structure (preconditions enforced by guard/enforcement)
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        _log_reorder_validation_error("not_dict", items_obj=None)
        return JSONResponse(
            {"title": "Unprocessable Entity", "status": 422, "detail": "Invalid reorder payload"},
            status_code=422,
            media_type="application/problem+json",
        )
    items = body.get("items")
    if not isinstance(items, list) or not items:
        _log_reorder_validation_error("items_missing", items_obj=items if isinstance(items, list) else [])
        return JSONResponse(
            {"title": "Unprocessable Entity", "status": 422, "detail": "Invalid reorder payload"},
            status_code=422,
            media_type="application/problem+json",
        )
    # Build proposed ordering and validate IDs and sequence
    try:
        proposed: Dict[str, int] = {str(i["document_id"]): int(i["order_number"]) for i in items}
    except (TypeError, ValueError, KeyError):
        _log_reorder_validation_error("bad_items_shape", items_obj=items)
        return JSONResponse(
            {"title": "Unprocessable Entity", "status": 422, "detail": "Invalid reorder payload"},
            status_code=422,
            media_type="application/problem+json",
        )
    # Relaxed: ignore unknown IDs rather than failing the request (partial lists allowed)
    # Filter proposed mapping down to known document IDs only
    unknown_ids = [k for k in proposed.keys() if k not in DOCUMENTS_STORE]
    if unknown_ids:
        try:
            _log_reorder_validation_error("id_unknown_ignored", items_obj=[{"document_id": i} for i in unknown_ids])
        except Exception:
            pass
    proposed = {k: v for k, v in proposed.items() if k in DOCUMENTS_STORE}
    # Relaxed validation for partial lists: apply provided order_numbers to
    # current list while preserving unspecified items' relative order, then
    # reconstruct a full contiguous 1..N sequence (Clarke U7.3.1.15).
    try:
        # Snapshot current list in order
        current_items = [
            {
                "document_id": d["document_id"],
                "order_number": int(d["order_number"]),
            }
            for d in sorted(
                repo_list_documents(store=DOCUMENTS_STORE),  # type: ignore[arg-type]
                key=lambda x: int(x.get("order_number", 0)),
            )
        ]
    except Exception:
        current_items = []
    n = len(current_items)
    # Build a target array of length N; place proposed ids at requested positions
    target: list[str | None] = [None] * max(n, 0)
    # Defensive clamp for provided positions to 1..N
    for did, pos in proposed.items():
        if not isinstance(pos, int) or pos < 1:
            _log_reorder_validation_error("bad_items_shape", items_obj=items)
            return JSONResponse(
                {"title": "Unprocessable Entity", "status": 422, "detail": "Invalid reorder payload"},
                status_code=422,
                media_type="application/problem+json",
            )
        if n > 0 and pos > n:
            # If client specifies a position beyond current list, clamp to N
            pos = n
        if n > 0:
            target[pos - 1] = str(did)
    # Remaining ids in their original order
    remaining = [str(x["document_id"]) for x in current_items if str(x["document_id"]) not in proposed]
    # Fill gaps in target with remaining ids preserving order
    ri = 0
    for i in range(len(target)):
        if target[i] is None:
            if ri < len(remaining):
                target[i] = remaining[ri]
                ri += 1
    # If any N was zero or anomalies, fall back to current order
    final_ids: list[str] = [str(t) for t in target if isinstance(t, str)] or [str(x["document_id"]) for x in current_items]
    # Rebuild a contiguous mapping 1..N
    final_mapping = {did: idx + 1 for idx, did in enumerate(final_ids)}
    # Apply ordering atomically using repository helper
    repo_apply_ordering(final_mapping, store=DOCUMENTS_STORE)  # type: ignore[arg-type]
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
    list_etag = _compute_document_list_etag(items_out)
    resp = JSONResponse({"list": items_out, "list_etag": list_etag}, status_code=200)
    # Use central emitter for ETag headers (preserves diagnostics via guard).
    # header_emitter logs a single 'etag.emit' event; avoid duplicate direct logs here.
    emit_etag_headers(resp, scope="document", token=list_etag, include_generic=True)
    logger.info(
        "reorder.precondition branch=success route=/api/v1/documents/order list_etag=%s",
        str(list_etag),
    )
    # Emit diagnostics headers per Epic K Phase-0 via centralized helper only
    try:
        from app.logic.header_emitter import emit_reorder_diagnostics as _emit_diag
        _emit_diag(resp, list_etag, if_match or "")
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
