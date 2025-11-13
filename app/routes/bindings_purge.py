"""Epic D – Bindings purge endpoint.

Removes all placeholders for a given document id and clears now-empty
question models. Returns JSON counters or 404 ProblemDetails when the
document is unknown and there are no placeholders to purge.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, Header
from fastapi.responses import JSONResponse
import logging
from app.logic.placeholders import purge_bindings
from app.logic.header_emitter import emit_etag_headers


router = APIRouter()
logger = logging.getLogger(__name__)

# Schema references for architectural visibility
SCHEMA_PURGE_REQUEST = "schemas/purge_request.schema.json"
SCHEMA_PURGE_RESPONSE = "schemas/purge_response.schema.json"


def _not_implemented(detail: str = "") -> JSONResponse:
    payload = {"title": "Not implemented", "status": 501}
    if detail:
        payload["detail"] = detail
    return JSONResponse(payload, status_code=501, media_type="application/problem+json")


@router.post(
    "/documents/{id}/bindings:purge",
    summary="Purge bindings for a document",
    description=(
        f"accepts {SCHEMA_PURGE_REQUEST}; returns {SCHEMA_PURGE_RESPONSE}"
    ),
)
def post_document_bindings_purge(id: str) -> Response:  # noqa: D401
    """Purge in-memory placeholders associated with a given document id.

    Contract:
    - Unknown document ids MUST return 404 ProblemDetails, except the explicit
      no-op id 'doc-noop' which returns 200 with zero counters.
    - Known documents return 200 with JSON counters for deleted placeholders
      and affected questions.
    """
    logger.info("purge_bindings:start document_id=%s", id)
    payload, not_found = purge_bindings(id)
    if not_found:
        logger.error("purge_bindings:not_found document_id=%s", id)
        problem = {"title": "not found", "status": 404, "detail": "resource not found"}
        return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    logger.info(
        "purge_bindings:complete document_id=%s deleted=%s updated_questions=%s",
        id,
        payload.get("deleted_placeholders"),
        payload.get("updated_questions"),
    )
    resp = JSONResponse(payload, status_code=200)
    # Clarke 7.1.5: use central emitter for ETag headers on mutations
    emit_etag_headers(resp, scope="generic", token='"skeleton-etag"', include_generic=True)
    return resp


__all__ = [
    "router",
    "post_document_bindings_purge",
]
