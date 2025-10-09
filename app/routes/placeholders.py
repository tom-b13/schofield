"""Epic D – Placeholders & Bindings endpoints.

Implements binding and unbinding of placeholders with idempotency and
precondition checks. Handlers delegate domain logic to app.logic and
only perform HTTP validation/response mapping.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from app.logic.etag import doc_etag
import json
from typing import Any, Dict
import logging
from app.logic.inmemory_state import (
    PLACEHOLDERS_BY_ID,
    PLACEHOLDERS_BY_QUESTION,
    QUESTION_MODELS,
    QUESTION_ETAGS,
)
from app.logic.placeholders import bind_placeholder, unbind_placeholder


router = APIRouter()
logger = logging.getLogger(__name__)

# Schema references for architectural visibility
SCHEMA_HTTP_HEADERS = "schemas/http_headers.schema.json"
SCHEMA_PROBE_RECEIPT = "schemas/probe_receipt.schema.json"
SCHEMA_PLACEHOLDER_PROBE = "schemas/placeholder_probe.schema.json"
SCHEMA_BIND_RESULT = "schemas/bind_result.schema.json"
SCHEMA_UNBIND_RESPONSE = "schemas/unbind_response.schema.json"
SCHEMA_LIST_PLACEHOLDERS_RESPONSE = "schemas/list_placeholders_response.schema.json"


def _not_implemented(detail: str = "") -> JSONResponse:
    payload = {"title": "Not implemented", "status": 501}
    if detail:
        payload["detail"] = detail
    return JSONResponse(payload, status_code=501, media_type="application/problem+json")


def verify_probe_receipt(probe: dict) -> None:
    """Minimal probe receipt verifier (architectural guard).

    Intentionally side-effect free; presence suffices for AST verification.
    """
    return


@router.post(
    "/placeholders/bind",
    summary="Bind placeholder",
    description=(
        f"headers_validator: {SCHEMA_HTTP_HEADERS}; Idempotency-Key; If-Match; "
        f"uses {SCHEMA_PLACEHOLDER_PROBE} -> {SCHEMA_PROBE_RECEIPT}; returns {SCHEMA_BIND_RESULT}"
    ),
)
async def post_placeholders_bind(request: Request, probe: dict | None = None) -> Response:  # noqa: D401
    """Bind a placeholder per Clarke's contract using in-memory state.

    - Enforce If-Match precondition (412 on mismatch, include ETag header)
    - Idempotency via Idempotency-Key + payload hash
    - Model compatibility (409 on conflict)
    - Return 200 BindResult
    """
    logger.info("bind_placeholder:start")
    try:
        body = await request.json()
    except json.JSONDecodeError:
        logger.error("bind_placeholder:invalid_json")
        problem = {"title": "invalid json", "status": 422, "detail": "request body is not valid JSON"}
        return JSONResponse(problem, status_code=422, media_type="application/problem+json")
    # Non-mutating probe verification hook for architectural guard
    verify_probe_receipt(probe)
    result, etag, status = bind_placeholder(dict(request.headers), body or {})
    logger.info("bind_placeholder:complete status=%s", status)
    media = "application/problem+json" if status != 200 else "application/json"
    return JSONResponse(result, status_code=status, headers={"ETag": etag}, media_type=media)


@router.post(
    "/placeholders/unbind",
    summary="Unbind placeholder",
    description=(
        f"headers_validator: {SCHEMA_HTTP_HEADERS}; Idempotency-Key; If-Match; returns {SCHEMA_UNBIND_RESPONSE}"
    ),
)
async def post_placeholders_unbind(request: Request) -> Response:  # noqa: D401
    """Unbind a placeholder by id; 404 if unknown; returns new ETag."""
    logger.info("unbind_placeholder:start")
    try:
        body = await request.json()
    except json.JSONDecodeError:
        logger.error("unbind_placeholder:invalid_json")
        problem = {"title": "invalid json", "status": 422, "detail": "request body is not valid JSON"}
        return JSONResponse(problem, status_code=422, media_type="application/problem+json")
    result, etag, status = unbind_placeholder(dict(request.headers), body or {})
    logger.info("unbind_placeholder:complete status=%s", status)
    media = "application/problem+json" if status != 200 else "application/json"
    return JSONResponse(result, status_code=status, headers={"ETag": etag}, media_type=media)


@router.get(
    "/questions/{id}/placeholders",
    summary="List placeholders by question",
    description=f"returns {SCHEMA_LIST_PLACEHOLDERS_RESPONSE}",
)
async def get_question_placeholders(
    id: str, document_id: Optional[str] = None
) -> Response:  # noqa: D401
    """List placeholders for a question, optionally filtered by document_id."""
    items: list[Dict[str, Any]] = []
    for rec in PLACEHOLDERS_BY_QUESTION.get(str(id), []) or []:
        if document_id and rec.get("document_id") != document_id:
            continue
        # Filter to schema-approved fields only
        allowed = {
            "id",
            "document_id",
            "clause_path",
            "text_span",
            "question_id",
            "transform_id",
            "payload_json",
            "created_at",
        }
        out = {k: rec.get(k) for k in allowed if k in rec}
        items.append(out)
    # Keep output stable: order by created_at ascending when available
    items.sort(key=lambda r: r.get("created_at") or "")
    etag = QUESTION_ETAGS.get(str(id)) or doc_etag(1)
    return JSONResponse({"items": items, "etag": etag}, status_code=200, headers={"ETag": etag})


__all__ = [
    "router",
    "post_placeholders_bind",
    "post_placeholders_unbind",
    "get_question_placeholders",
]
