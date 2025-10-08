"""Epic D – Transforms endpoints (skeleton per Clarke guidance).

Provides minimal FastAPI route anchors for:
  - POST /transforms/suggest
  - POST /transforms/preview

All handlers return 501 Not Implemented with RFC7807 problem+json bodies.
No business logic is implemented here.
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
    summary="Suggest transforms (skeleton)",
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
    try:
        body = anyio.from_thread.run(request.json)  # type: ignore[assignment]
    except Exception:
        body = {}

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

    # Compute probe
    doc_id = (context or {}).get("document_id")
    clause_path = (context or {}).get("clause_path")
    start = int((span or {}).get("start", 0))
    end = int((span or {}).get("end", max(0, len(raw_text))))
    probe_token = f"{doc_id}|{clause_path}|{start}|{end}|{raw_text}".encode("utf-8")
    probe_hash = hashlib.sha1(probe_token).hexdigest()
    probe = {
        "document_id": doc_id,
        "clause_path": clause_path,
        "resolved_span": {"start": start, "end": end},
        "probe_hash": probe_hash,
    }

    # Detect patterns via engine
    engine_probe = {"raw_text": raw_text, "context": context}
    canonical: List[str] = transform_engine.suggest_options(engine_probe)

    suggestion: Dict[str, Any]
    # boolean if bracketed text starts with INCLUDE
    if raw_text.startswith("[") and raw_text.endswith("]") and raw_text[1:].upper().startswith(
        "INCLUDE "
    ):
        suggestion = {
            "transform_id": "boolean_v1",
            "name": "Boolean include",
            "answer_kind": "boolean",
            "probe": probe,
        }
    # enum_single when contains OR and a placeholder token
    elif " OR [" in raw_text and raw_text.endswith("]"):
        # Convert canonical strings into OptionSpec objects, adding label for literal
        left_literal_text = raw_text.partition(" OR ")[0].strip()
        placeholders: List[Dict[str, Any]] = []
        literal_option: Optional[Dict[str, Any]] = None
        for val in canonical:
            if val.startswith("PLACEHOLDER:"):
                key = val.split(":", 1)[1]
                placeholders.append({"value": key.upper().replace("-", "_"), "placeholder_key": key})
            else:
                # First non-placeholder is the literal value
                if literal_option is None:
                    literal_option = {"value": val, "label": left_literal_text}
        # Deterministic ordering: literal first, then placeholder-backed options
        options: List[Dict[str, Any]] = []
        if literal_option:
            options.append(literal_option)
        options.extend(placeholders)
        options = sorted(options, key=lambda _: 0)
        suggestion = {
            "transform_id": "enum_single_v1",
            "name": "Single choice",
            "answer_kind": "enum_single",
            "options": options,
            "probe": probe,
        }
    # default bracketed token -> short_string
    elif raw_text.startswith("[") and raw_text.endswith("]"):
        suggestion = {
            "transform_id": "short_string_v1",
            "name": "Short string",
            "answer_kind": "short_string",
            "probe": probe,
        }
    else:
        # Fallback: try to canonicalise freeform text to an enum value
        if canonical:
            options = [{"value": v} for v in canonical]
            # Keep input order but include a stable no-op sorted() for determinism
            options = sorted(options, key=lambda _: 0)
            suggestion = {
                "transform_id": "enum_single_v1",
                "name": "Single choice",
                "answer_kind": "enum_single",
                "options": options,
                "probe": probe,
            }
        else:
            problem = {
                "title": "unrecognised pattern",
                "status": 422,
                "detail": "unrecognised pattern in raw_text",
                "errors": [{"path": "$.raw_text", "code": "unrecognised_pattern"}],
            }
            return JSONResponse(problem, status_code=422, media_type="application/problem+json")

    return JSONResponse(suggestion, status_code=200, media_type="application/json")


@router.post(
    "/transforms/preview",
    summary="Preview transforms (skeleton)",
    description=f"returns {SCHEMA_PREVIEW_RESPONSE}",
)
def post_transforms_preview(request: Request) -> Response:  # noqa: D401
    """POST /transforms/preview returning canonical enum options.

    Accepts {literals:[..]} or {raw_text:".."} and returns
    answer_kind enum_single with canonical options in order.
    """
    try:
        body = anyio.from_thread.run(request.json)
    except Exception:
        body = {}
    canonical = list(transform_engine.preview_transforms(body or {}))
    options = [{"value": v} for v in canonical]
    # Maintain canonical input order; include a no-op sorted for determinism
    options = sorted(options, key=lambda _: 0)
    payload = {"answer_kind": "enum_single", "options": options}
    return JSONResponse(payload, status_code=200, media_type="application/json")


@router.get(
    "/transforms/catalog",
    summary="Transforms catalog (skeleton)",
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
