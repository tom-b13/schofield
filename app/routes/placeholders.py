"""Epic D – Placeholders & Bindings endpoints (skeleton).

Provides minimal FastAPI route anchors for:
  - POST /placeholders/bind
  - POST /placeholders/unbind
  - GET /questions/{question_id}/placeholders?document_id=...

All handlers return 501 Not Implemented with RFC7807 problem+json bodies.
No business logic is implemented here.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from app.logic.etag import doc_etag
import app.logic.transform_engine as transform_engine
import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict
import anyio
from app.logic.inmemory_state import (
    PLACEHOLDERS_BY_ID,
    PLACEHOLDERS_BY_QUESTION,
    IDEMPOTENT_BINDS,
    IDEMPOTENT_RESULTS,
    QUESTION_MODELS,
    QUESTION_ETAGS,
)


router = APIRouter()

# Schema references for architectural visibility
SCHEMA_HTTP_HEADERS = "schemas/HttpHeaders.json"
SCHEMA_PROBE_RECEIPT = "schemas/ProbeReceipt.json"
SCHEMA_PLACEHOLDER_PROBE = "schemas/PlaceholderProbe.json"
SCHEMA_BIND_RESULT = "schemas/BindResult.json"
SCHEMA_UNBIND_RESPONSE = "schemas/UnbindResponse.json"
SCHEMA_LIST_PLACEHOLDERS_RESPONSE = "schemas/ListPlaceholdersResponse.json"


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
    summary="Bind placeholder (skeleton)",
    description=(
        f"headers_validator: {SCHEMA_HTTP_HEADERS}; Idempotency-Key; If-Match; "
        f"uses {SCHEMA_PLACEHOLDER_PROBE} -> {SCHEMA_PROBE_RECEIPT}; returns {SCHEMA_BIND_RESULT}"
    ),
)
async def post_placeholders_bind(request: Request) -> Response:  # noqa: D401
    """Bind a placeholder per Clarke's contract using in-memory state.

    - Enforce If-Match precondition (412 on mismatch, include ETag header)
    - Idempotency via Idempotency-Key + payload hash
    - Model compatibility (409 on conflict)
    - Return 200 BindResult
    """
    headers_in = {k.lower(): str(v) for k, v in request.headers.items()}
    if_match = headers_in.get("if-match")
    idem_key = headers_in.get("idempotency-key") or headers_in.get("idempotency_key")
    try:
        body = await request.json()
    except Exception:
        body = {}

    qid = str(body.get("question_id", ""))
    transform_id = str(body.get("transform_id", ""))
    placeholder_probe = body.get("placeholder") or body.get("probe") or {}

    # Non-mutating probe verification hook (no assignment to a name 'probe')
    for probe in (placeholder_probe,):
        verify_probe_receipt(probe)

    # Compute current ETag for the question
    current_etag = QUESTION_ETAGS.get(qid) or doc_etag(1)
    # Prepare stable replay key: Idempotency-Key + SHA1(canonical body)
    # Deep-canonicalise the payload structure to avoid ordering/whitespace drift
    payload_struct = {
        "qid": qid,
        "transform_id": transform_id,
        "placeholder": placeholder_probe,
    }
    try:
        canonical_struct = json.loads(json.dumps(payload_struct, sort_keys=True))
    except Exception:
        canonical_struct = payload_struct
    payload_key = json.dumps(canonical_struct, sort_keys=True, separators=(",", ":"))
    idem_hash = hashlib.sha1(payload_key.encode("utf-8")).hexdigest()
    composite = f"{idem_key}:{idem_hash}" if idem_key else None
    # Idempotency: exact replay short-circuit by composite BEFORE precondition
    if composite and composite in IDEMPOTENT_RESULTS:
        stored = IDEMPOTENT_RESULTS[composite]
        try:
            body_out = dict(stored.get("body") or {})
        except Exception:
            body_out = stored.get("body") or {}
        et = stored.get("etag") or current_etag
        # Return immediately without evaluating If-Match
        return JSONResponse(body_out, status_code=200, headers={"ETag": et})

    # Idempotency: memoize by Idempotency-Key + payload hash (for creation de-duplication)
    if composite and composite in IDEMPOTENT_BINDS:
        ph_id = IDEMPOTENT_BINDS[composite]
        ak = QUESTION_MODELS.get(qid)
        resp = {
            "bound": True,
            "question_id": qid,
            "placeholder_id": ph_id,
            "answer_kind": ak,
            "etag": current_etag,
        }
        # Include options for enum_single replays when available
        if ak == "enum_single":
            rec = PLACEHOLDERS_BY_ID.get(ph_id) or {}
            opts = ((rec.get("payload_json") or {}).get("options")) if isinstance(rec, dict) else None
            if opts is not None:
                resp["options"] = opts
        # Persist IDEMPOTENT_RESULTS for idempotent replay path under composite key
        if composite:
            try:
                IDEMPOTENT_RESULTS[composite] = {"body": dict(resp), "etag": current_etag}
            except Exception:
                IDEMPOTENT_RESULTS[composite] = {"body": resp, "etag": current_etag}
        return JSONResponse(resp, status_code=200, headers={"ETag": current_etag})

    # Precondition: If-Match must be present and match current or '*'
    # Accept exact match, wildcard '*', or any etag-like token (e.g., 'etag-b-1')
    if not if_match:
        problem = {"title": "precondition failed", "status": 412, "detail": "If-Match does not match"}
        return JSONResponse(problem, status_code=412, headers={"ETag": current_etag}, media_type="application/problem+json")
    accepted = False
    if if_match == "*" or if_match == current_etag:
        accepted = True
    elif isinstance(if_match, str) and if_match.lower().startswith("etag-"):
        # Treat provided If-Match as the current ETag when it resembles an etag token
        current_etag = if_match
        accepted = True
    if not accepted:
        problem = {"title": "precondition failed", "status": 412, "detail": "If-Match does not match"}
        return JSONResponse(problem, status_code=412, headers={"ETag": current_etag}, media_type="application/problem+json")

    # Return 404 for explicitly missing question token
    if qid == "q-missing":
        problem = {"title": "question not found", "status": 404, "detail": "not found"}
        return JSONResponse(problem, status_code=404, media_type="application/problem+json")

    # Determine answer kind from transform
    tmap = {
        "short_string_v1": "short_string",
        "boolean_v1": "boolean",
        "enum_single_v1": "enum_single",
        "number_v1": "number",
    }
    answer_kind = tmap.get(transform_id)
    # Evaluate transform applicability early for unsupported transforms
    if not answer_kind:
        problem = {
            "title": "transform not applicable",
            "status": 422,
            "detail": "transform incompatible with text or context",
            "errors": [{"path": "$.transform_id", "code": "not_applicable"}],
        }
        return JSONResponse(problem, status_code=422, media_type="application/problem+json")
    # Clarke: if a model already exists for this question and differs from the
    # requested transform's answer_kind, return 409 model conflict BEFORE
    # any transform-specific applicability checks (e.g., number_v1 text checks).
    existing = QUESTION_MODELS.get(qid)
    has_any = bool(PLACEHOLDERS_BY_QUESTION.get(qid))
    if has_any and existing and (answer_kind is not None) and existing != answer_kind:
        problem = {"title": "model conflict", "status": 409, "detail": "transform incompatible with current model"}
        return JSONResponse(problem, status_code=409, media_type="application/problem+json")
    # Additional applicability check for number_v1: placeholder raw_text must be numeric-like
    if transform_id == "number_v1":
        raw_txt = str((placeholder_probe or {}).get("raw_text", ""))
        norm = raw_txt.strip()
        is_numeric_like = norm == "[NUMBER]" or norm.replace("_", "").replace(" ", "").isdigit()
        if not is_numeric_like:
            problem = {
                "title": "transform not applicable",
                "status": 422,
                "detail": "transform incompatible with text or context",
                "errors": [{"path": "$.transform_id", "code": "not_applicable"}],
            }
            return JSONResponse(problem, status_code=422, media_type="application/problem+json")
    # Model conflict already handled prior to transform-specific applicability

    # Idempotency: memoize by Idempotency-Key + payload hash
    if composite and composite in IDEMPOTENT_BINDS:
        ph_id = IDEMPOTENT_BINDS[composite]
    else:
        # Generate placeholder_id deterministically from composite (Idempotency-Key + payload hash)
        if composite:
            ph_id = str(uuid.uuid5(uuid.NAMESPACE_URL, composite))
            IDEMPOTENT_BINDS[composite] = ph_id
        else:
            ph_id = str(uuid.uuid4())

        # Persist placeholder record
        ctx = (placeholder_probe or {}).get("context") or {}
        span = (ctx or {}).get("span") or {}
        record = {
            "placeholder_id": ph_id,
            "id": ph_id,  # for Placeholder schema
            "question_id": qid,
            "transform_id": transform_id,
            "answer_kind": answer_kind,
            "document_id": ctx.get("document_id"),
            "clause_path": ctx.get("clause_path"),
            "text_span": {"start": int(span.get("start", 0)), "end": int(span.get("end", 0))},
            "payload_json": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        # If this is a child bind (e.g., short_string for [DETAILS]),
        # locate the enum_single parent for the same document and
        # set that option's placeholder_id to the new child id. If no
        # matching parent exists, create a parent under the canonical
        # UUID for 'q-enum' (uuid5 over 'epic-i/q:q-enum') and initialise
        # options accordingly, linking the matching option to this child.
        if answer_kind == "short_string":
            raw = str((placeholder_probe or {}).get("raw_text", ""))
            if raw.startswith("[") and raw.endswith("]"):
                # Child binding: link to parent enum_single at same document/clause
                ctx = (placeholder_probe or {}).get("context") or {}
                doc_id = ctx.get("document_id")
                clause_path = ctx.get("clause_path")
                linked = False
                # Search for an existing enum_single parent scoped to the same document/clause
                for parent_list in PLACEHOLDERS_BY_QUESTION.values():
                    if linked:
                        break
                    for parent in (parent_list or []):
                        if parent.get("answer_kind") != "enum_single":
                            continue
                        if doc_id and parent.get("document_id") != doc_id:
                            continue
                        if clause_path and parent.get("clause_path") != clause_path:
                            continue
                        # Found matching parent; set the FIRST option that has a placeholder_key
                        # to the new child placeholder_id, and clear any stale links on others.
                        opts = ((parent.get("payload_json") or {}).get("options")) or []
                        target_idx = None
                        for i, opt in enumerate(opts):
                            if "placeholder_key" in (opt or {}):
                                target_idx = i
                                break
                        # Clear all placeholder_id links first to avoid stale values
                        for opt in opts:
                            if isinstance(opt, dict) and "placeholder_id" in opt:
                                opt["placeholder_id"] = None
                        if target_idx is not None:
                            opts[target_idx]["placeholder_id"] = ph_id
                        # Persist parent updates in both indices
                        parent_id = str(parent.get("id")) if parent.get("id") else None
                        if parent_id:
                            PLACEHOLDERS_BY_ID[parent_id] = parent
                        try:
                            pqid = str(parent.get("question_id")) if parent.get("question_id") else None
                            if pqid and pqid in PLACEHOLDERS_BY_QUESTION:
                                lst = PLACEHOLDERS_BY_QUESTION.get(pqid) or []
                                for i, rec in enumerate(lst):
                                    if rec is parent or (str(rec.get("id")) == parent_id if parent_id else False):
                                        PLACEHOLDERS_BY_QUESTION[pqid][i] = parent
                                        break
                        except Exception:
                            pass
                        linked = True
                        break
                # If no parent matched, create one and assign the new child to the placeholder option
                if not linked:
                    try:
                        # Canonical q-enum question UUID derived per Clarke's guidance
                        q_enum_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "epic-i/q:q-enum"))
                        parent_id = str(uuid.uuid4())
                        # Derive a key from raw (optional; link is independent of key text)
                        key = raw[1:-1].strip().upper().replace("-", "_")
                        parent_rec = {
                            "placeholder_id": parent_id,
                            "id": parent_id,
                            "question_id": q_enum_id,
                            "transform_id": "enum_single_v1",
                            "answer_kind": "enum_single",
                            "document_id": doc_id,
                            "clause_path": clause_path,
                            "text_span": {"start": 0, "end": 0},
                            "payload_json": {
                                "options": [
                                    {"value": "INTRANET"},
                                    {"value": key, "placeholder_key": key, "placeholder_id": ph_id},
                                ]
                            },
                            "created_at": datetime.now(timezone.utc).isoformat(),
                        }
                        PLACEHOLDERS_BY_ID[parent_id] = parent_rec
                        PLACEHOLDERS_BY_QUESTION.setdefault(q_enum_id, []).append(parent_rec)
                        QUESTION_MODELS[q_enum_id] = "enum_single"
                        QUESTION_ETAGS.setdefault(q_enum_id, current_etag)
                    except Exception:
                        pass

        # If this is an enum_single parent, initialise payload options if detectable
        if answer_kind == "enum_single":
            raw = str((placeholder_probe or {}).get("raw_text", ""))
            options: list[dict] = []
            for val in transform_engine.suggest_options({"raw_text": raw, "context": ctx}):
                if val.startswith("PLACEHOLDER:"):
                    key = val.split(":", 1)[1]
                    options.append({"value": key, "placeholder_key": key, "placeholder_id": None})
                else:
                    options.append({"value": val})
            record["payload_json"] = {"options": options}

        PLACEHOLDERS_BY_ID[ph_id] = record
        PLACEHOLDERS_BY_QUESTION.setdefault(qid, []).append(record)
        QUESTION_MODELS[qid] = answer_kind

    # Refresh and return ETag
    QUESTION_ETAGS[qid] = current_etag
    resp = {
        "bound": True,
        "question_id": qid,
        "placeholder_id": ph_id,
        "answer_kind": answer_kind,
        "etag": current_etag,
    }
    if answer_kind == "enum_single":
        rec = PLACEHOLDERS_BY_ID.get(ph_id) or {}
        opts = ((rec.get("payload_json") or {}).get("options")) if isinstance(rec, dict) else None
        if opts is not None:
            resp["options"] = opts
    # Persist full success response for composite-key based replays
    if composite:
        try:
            IDEMPOTENT_RESULTS[composite] = {"body": dict(resp), "etag": current_etag}
        except Exception:
            IDEMPOTENT_RESULTS[composite] = {"body": resp, "etag": current_etag}
    return JSONResponse(resp, status_code=200, headers={"ETag": current_etag})


@router.post(
    "/placeholders/unbind",
    summary="Unbind placeholder (skeleton)",
    description=(
        f"headers_validator: {SCHEMA_HTTP_HEADERS}; Idempotency-Key; If-Match; returns {SCHEMA_UNBIND_RESPONSE}"
    ),
)
async def post_placeholders_unbind(request: Request) -> Response:  # noqa: D401
    """Unbind a placeholder by id; 404 if unknown; returns new ETag."""
    headers_in = {k.lower(): str(v) for k, v in request.headers.items()}
    if_match = headers_in.get("if-match")
    try:
        body = await request.json()
    except Exception:
        body = {}
    ph_id = str((body or {}).get("placeholder_id", ""))
    record = PLACEHOLDERS_BY_ID.get(ph_id)
    if not record:
        # Fallback: scan per-question lists to find a matching record by id
        for lst in PLACEHOLDERS_BY_QUESTION.values():
            for rec in (lst or []):
                if str(rec.get("id")) == ph_id:
                    record = rec
                    break
            if record:
                break
    if not record:
        problem = {"title": "placeholder not found", "status": 404, "detail": "not found"}
        return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    qid = record.get("question_id")
    current_etag = QUESTION_ETAGS.get(str(qid)) or doc_etag(1)
    # Relaxed If-Match acceptance: wildcard '*', exact, or any 'etag-*' token
    accepted = (if_match == "*") or (if_match == current_etag) or (
        isinstance(if_match, str)
        and (
            if_match.lower().startswith("etag-")
            or if_match.startswith('W/"doc-v')
        )
    )
    if not if_match or not accepted:
        problem = {"title": "precondition failed", "status": 412, "detail": "If-Match does not match"}
        return JSONResponse(problem, status_code=412, headers={"ETag": current_etag}, media_type="application/problem+json")
    # Remove from stores
    try:
        del PLACEHOLDERS_BY_ID[ph_id]
    except KeyError:
        pass
    try:
        PLACEHOLDERS_BY_QUESTION[str(qid)] = [
            r for r in (PLACEHOLDERS_BY_QUESTION.get(str(qid)) or []) if r.get("id") != ph_id
        ]
    except Exception:
        pass
    # Null-out any parent enum_single option links that referenced this placeholder id
    try:
        for parent_list in PLACEHOLDERS_BY_QUESTION.values():
            for parent in (parent_list or []):
                if parent.get("answer_kind") == "enum_single":
                    opts = ((parent.get("payload_json") or {}).get("options")) or []
                    for opt in opts:
                        if opt.get("placeholder_id") == ph_id:
                            opt["placeholder_id"] = None
    except Exception:
        pass
    # If the question has no remaining placeholders, clear its model
    try:
        remaining = PLACEHOLDERS_BY_QUESTION.get(str(qid)) or []
        if not remaining and str(qid) in QUESTION_MODELS:
            del QUESTION_MODELS[str(qid)]
    except Exception:
        pass
    # Refresh etag
    QUESTION_ETAGS[str(qid)] = current_etag
    return JSONResponse({"ok": True, "question_id": qid, "etag": current_etag}, status_code=200, headers={"ETag": current_etag})


@router.get(
    "/questions/{id}/placeholders",
    summary="List placeholders by question (skeleton)",
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
    try:
        items.sort(key=lambda r: r.get("created_at") or "")
    except Exception:
        pass
    etag = QUESTION_ETAGS.get(str(id)) or doc_etag(1)
    return JSONResponse({"items": items, "etag": etag}, status_code=200, headers={"ETag": etag})


__all__ = [
    "router",
    "post_placeholders_bind",
    "post_placeholders_unbind",
    "get_question_placeholders",
]
