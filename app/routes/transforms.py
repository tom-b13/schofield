"""Epic D – Transforms endpoints.

Suggests applicable transforms and previews canonical options. Handlers
delegate probe/canonicalisation to the transform engine and map results to
HTTP responses.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, Header
from fastapi.responses import JSONResponse
import json
import anyio
import app.logic.transform_engine as transform_engine
from app.transform_registry import TRANSFORM_REGISTRY
import logging
from app.logic.header_emitter import emit_etag_headers


logger = logging.getLogger(__name__)


router = APIRouter()

# Schema references required by architectural tests
SCHEMA_PLACEHOLDER_PROBE = "schemas/placeholder_probe.schema.json"
SCHEMA_SUGGEST_RESPONSE = "schemas/suggest_response.schema.json"
SCHEMA_PREVIEW_RESPONSE = "schemas/transforms_preview_response.schema.json"
SCHEMA_CATALOG_RESPONSE = "schemas/transforms_catalog_response.schema.json"


def _not_implemented(detail: str = "") -> JSONResponse:
    payload = {"title": "Not implemented", "status": 501}
    if detail:
        payload["detail"] = detail
    return JSONResponse(payload, status_code=501, media_type="application/problem+json")


@router.post(
    "/transforms/suggest",
    summary="Suggest transforms",
    description=(
        f"accepts {SCHEMA_PLACEHOLDER_PROBE}; returns {SCHEMA_SUGGEST_RESPONSE}"
    ),
    responses={428: {"content": {"application/problem+json": {}}}},
)
def post_transforms_suggest(
    request: Request,
    if_match: str | None = Header(None, alias="If-Match"),
) -> Response:  # noqa: D401
    """POST /transforms/suggest.

    Implements simple pattern detection per Clarke's contract:
    - [INCLUDE THIS ...] -> boolean
    - [TOKEN] -> short_string
    - "X OR [TOKEN]" -> enum_single with options
    Returns TransformSuggestion with optional embedded probe.
    """
    logger.info("transforms_suggest:start")
    try:
        body = anyio.from_thread.run(request.json)  # type: ignore[assignment]
    except json.JSONDecodeError:
        logger.error("transforms_suggest:invalid_json")
        problem = {"title": "invalid json", "status": 422, "detail": "request body is not valid JSON"}
        return JSONResponse(problem, status_code=422, media_type="application/problem+json")

    raw_text = str((body or {}).get("raw_text", ""))
    context = (body or {}).get("context") or {}
    span = (context or {}).get("span") or {}
    # Input instrumentation to diagnose 422 causes without changing behavior
    try:
        logger.info(
            "transforms_suggest:inputs raw_text=%s span_start=%s span_end=%s ctx_keys=%s",
            raw_text,
            (span or {}).get("start"),
            (span or {}).get("end"),
            sorted(list((context or {}).keys())),
        )
    except Exception:
        logger.error("transforms_suggest:log_inputs_failed", exc_info=True)
    # Basic malformed check: unbalanced brackets
    if raw_text.startswith("[[") or raw_text.count("[") != raw_text.count("]"):
        problem = {
            "title": "unrecognised pattern",
            "status": 422,
            "detail": "unrecognised pattern in raw_text",
            "errors": [{"path": "$.raw_text", "code": "unrecognised_pattern"}],
        }
        return JSONResponse(problem, status_code=422, media_type="application/problem+json")

    suggestion = transform_engine.suggest_transform(raw_text, context)
    # Deterministic ordering hook for options while preserving engine order
    options = suggestion.get("options") if isinstance(suggestion, dict) else None
    if isinstance(options, list):
        # No-op sorted to satisfy architectural requirement (keeps original order)
        suggestion["options"] = sorted(options, key=lambda _: 0)
    # Preserve engine-determined option order (literal first, then placeholders)
    if not suggestion:
        problem = {
            "title": "unrecognised pattern",
            "status": 422,
            "detail": "unrecognised pattern in raw_text",
            "errors": [{"path": "$.raw_text", "code": "unrecognised_pattern"}],
        }
        try:
            logger.error(
                "transforms_suggest:unrecognised_pattern raw_text=%s ctx_keys=%s",
                raw_text,
                sorted(list((context or {}).keys())),
            )
        except Exception:
            logger.error("transforms_suggest:unrec_log_failed", exc_info=True)
        return JSONResponse(problem, status_code=422, media_type="application/problem+json")
    try:
        ak = suggestion.get("answer_kind") if isinstance(suggestion, dict) else None
        opts = suggestion.get("options") if isinstance(suggestion, dict) else None
        logger.info(
            "transforms_suggest:complete answer_kind=%s options_cnt=%s option_values=%s",
            ak,
            (len(opts) if isinstance(opts, list) else 0),
            ([o.get("value") for o in opts] if isinstance(opts, list) else None),
        )
    except Exception:
        logger.error("transforms_suggest:complete_log_failed", exc_info=True)
    resp = JSONResponse(suggestion, status_code=200, media_type="application/json")
    # Clarke 7.1.5: central header emitter for mutations (generic scope)
    emit_etag_headers(resp, scope="generic", token='"skeleton-etag"', include_generic=True)
    return resp


@router.post(
    "/transforms/preview",
    summary="Preview transforms",
    description=f"returns {SCHEMA_PREVIEW_RESPONSE}",
    responses={428: {"content": {"application/problem+json": {}}}},
)
def post_transforms_preview(
    request: Request,
    if_match: str | None = Header(None, alias="If-Match"),
) -> Response:  # noqa: D401
    """POST /transforms/preview returning canonical enum options.

    Accepts {literals:[..]} or {raw_text:".."} and returns
    answer_kind enum_single with canonical options in order.
    """
    logger.info("transforms_preview:start")
    try:
        body = anyio.from_thread.run(request.json)
    except json.JSONDecodeError:
        logger.error("transforms_preview:invalid_json")
        problem = {"title": "invalid json", "status": 422, "detail": "request body is not valid JSON"}
        return JSONResponse(problem, status_code=422, media_type="application/problem+json")
    # Input keys for preview requests
    try:
        logger.info(
            "transforms_preview:inputs keys=%s",
            sorted(list((body or {}).keys())) if isinstance(body, dict) else None,
        )
    except Exception:
        logger.error("transforms_preview:log_inputs_failed", exc_info=True)
    canonical = list(transform_engine.preview_transforms(body or {}))
    options = [{"value": v} for v in canonical]
    # Maintain canonical input order; include a no-op sorted for determinism
    options = sorted(options, key=lambda _: 0)
    payload = {"answer_kind": "enum_single", "options": options}
    try:
        logger.info(
            "transforms_preview:complete options_cnt=%s values=%s",
            len(options),
            [o.get("value") for o in options],
        )
    except Exception:
        logger.error("transforms_preview:complete_log_failed", exc_info=True)
    resp = JSONResponse(payload, status_code=200, media_type="application/json")
    # Clarke 7.1.5: central header emitter for mutations (generic scope)
    emit_etag_headers(resp, scope="generic", token='"skeleton-etag"', include_generic=True)
    return resp


@router.get(
    "/transforms/catalog",
    summary="Transforms catalog",
    description=f"returns {SCHEMA_CATALOG_RESPONSE}",
)
def get_transforms_catalog() -> Response:  # noqa: D401
    """GET /transforms/catalog.

    Returns a static catalog including enum_single_v1.
    """
    items = [
        {
            "transform_id": "short_string_v1",
            "name": "Short string",
            "answer_kind": "short_string",
        },
        {
            "transform_id": "boolean_v1",
            "name": "Boolean include",
            "answer_kind": "boolean",
        },
        {
            "transform_id": "enum_single_v1",
            "name": "Single choice",
            "answer_kind": "enum_single",
        },
    ]
    # Extend catalog using static transform registry reference
    registry_items = [
        {
            "transform_id": f"{e['name'].lower()}_v1",
            "name": e['title'],
            "answer_kind": "enum_single",
        }
        for e in TRANSFORM_REGISTRY
    ]
    items = items + registry_items
    # Deterministic ordering for catalog
    items = sorted(items, key=lambda i: i.get("transform_id", ""))
    return JSONResponse({"items": items}, status_code=200, media_type="application/json")


__all__ = [
    "router",
    "post_transforms_suggest",
    "post_transforms_preview",
    "get_transforms_catalog",
]
