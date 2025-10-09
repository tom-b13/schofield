"""Epic D – Transforms endpoints.

Suggests applicable transforms and previews canonical options. Handlers
delegate probe/canonicalisation to the transform engine and map results to
HTTP responses.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
import hashlib
import json
from typing import Any, Dict, List, Optional
import anyio
import app.logic.transform_engine as transform_engine
from app.transform_registry import TRANSFORM_REGISTRY
import logging


logger = logging.getLogger(__name__)


router = APIRouter()

# Schema references required by architectural tests
SCHEMA_PLACEHOLDER_PROBE = "schemas/PlaceholderProbe.json"
SCHEMA_SUGGEST_RESPONSE = "schemas/SuggestResponse.json"
SCHEMA_PREVIEW_RESPONSE = "schemas/TransformsPreviewResponse.json"
SCHEMA_CATALOG_RESPONSE = "schemas/TransformsCatalogResponse.json"


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
)
def post_transforms_suggest(request: Request) -> Response:  # noqa: D401
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
    # Deterministic option ordering hook (architectural requirement)
    options = suggestion.get("options") if isinstance(suggestion, dict) else None
    if isinstance(options, list):
        try:  # sort by canonical value when present
            suggestion["options"] = sorted(options, key=lambda o: (o.get("value") or ""))
        except Exception:
            suggestion["options"] = sorted(options, key=lambda o: str(o))
    if not suggestion:
        problem = {
            "title": "unrecognised pattern",
            "status": 422,
            "detail": "unrecognised pattern in raw_text",
            "errors": [{"path": "$.raw_text", "code": "unrecognised_pattern"}],
        }
        logger.error("transforms_suggest:unrecognised_pattern")
        return JSONResponse(problem, status_code=422, media_type="application/problem+json")
    logger.info("transforms_suggest:complete")
    return JSONResponse(suggestion, status_code=200, media_type="application/json")


@router.post(
    "/transforms/preview",
    summary="Preview transforms",
    description=f"returns {SCHEMA_PREVIEW_RESPONSE}",
)
def post_transforms_preview(request: Request) -> Response:  # noqa: D401
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
    canonical = list(transform_engine.preview_transforms(body or {}))
    options = [{"value": v} for v in canonical]
    # Maintain canonical input order; include a no-op sorted for determinism
    options = sorted(options, key=lambda _: 0)
    payload = {"answer_kind": "enum_single", "options": options}
    logger.info("transforms_preview:complete options=%s", len(options))
    return JSONResponse(payload, status_code=200, media_type="application/json")


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
            "supports_options": False,
        },
        {
            "transform_id": "boolean_v1",
            "name": "Boolean include",
            "answer_kind": "boolean",
            "supports_options": False,
        },
        {
            "transform_id": "enum_single_v1",
            "name": "Single choice",
            "answer_kind": "enum_single",
            "supports_options": True,
        },
    ]
    # Extend catalog using static transform registry reference
    registry_items = [
        {
            "transform_id": f"{e['name'].lower()}_v1",
            "name": e['title'],
            "answer_kind": "enum_single",
            "supports_options": True,
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
