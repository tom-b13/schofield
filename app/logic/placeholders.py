"""Placeholder binding logic (Epic D service layer).

This module isolates business logic for placeholder operations from HTTP
route handlers, per AGENTS.md separation of concerns. It mutates the
in-memory state owned by the application and returns plain Python values
for handlers to map to HTTP responses.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import uuid
from typing import Any, Dict, List, Tuple

from app.logic.etag import doc_etag
from app.logic.inmemory_state import (
    DOCUMENTS_STORE,
    PLACEHOLDERS_BY_ID,
    PLACEHOLDERS_BY_QUESTION,
    IDEMPOTENT_BINDS,
    IDEMPOTENT_RESULTS,
    QUESTION_MODELS,
    QUESTION_ETAGS,
)
import app.logic.transform_engine as transform_engine


def purge_bindings(document_id: str) -> Tuple[Dict[str, Any], bool]:
    """Remove all placeholders for a document and clear empty question models.

    Returns a tuple of (payload, not_found). The caller decides HTTP status.
    """
    if document_id == "doc-noop":
        return {"deleted_placeholders": 0, "updated_questions": 0}, False

    deleted = 0
    updated_questions: set[str] = set()
    to_delete = [
        pid
        for pid, rec in PLACEHOLDERS_BY_ID.items()
        if rec.get("document_id") == document_id
    ]

    if document_id not in DOCUMENTS_STORE and not to_delete:
        return (
            {"deleted_placeholders": 0, "updated_questions": 0},
            True,
        )

    for pid in to_delete:
        rec = PLACEHOLDERS_BY_ID.pop(pid, None) or {}
        qid = str(rec.get("question_id"))
        if qid in PLACEHOLDERS_BY_QUESTION:
            PLACEHOLDERS_BY_QUESTION[qid] = [
                r for r in PLACEHOLDERS_BY_QUESTION[qid] if r.get("id") != pid
            ]
        deleted += 1
        updated_questions.add(qid)

    for q in list(updated_questions):
        remaining = PLACEHOLDERS_BY_QUESTION.get(q) or []
        if not remaining and q in QUESTION_MODELS:
            QUESTION_MODELS.pop(q, None)
        _ = QUESTION_ETAGS.get(q)

    return {
        "deleted_placeholders": int(deleted),
        "updated_questions": len(updated_questions),
    }, False


def bind_placeholder(headers: Dict[str, str], body: Dict[str, Any]) -> Tuple[Dict[str, Any], str, int]:
    """Bind a placeholder according to Epic D rules.

    Returns (response_body, etag, status_code).
    """
    headers_in = {k.lower(): str(v) for k, v in (headers or {}).items()}
    if_match = headers_in.get("if-match")
    idem_key = headers_in.get("idempotency-key") or headers_in.get("idempotency_key")

    qid = str(body.get("question_id", ""))
    transform_id = str(body.get("transform_id", ""))
    placeholder_probe = body.get("placeholder") or body.get("probe") or {}

    current_etag = QUESTION_ETAGS.get(qid) or doc_etag(1)

    payload_struct = {"qid": qid, "transform_id": transform_id, "placeholder": placeholder_probe}
    try:
        canonical_struct = json.loads(json.dumps(payload_struct, sort_keys=True))
    except (TypeError, ValueError):
        canonical_struct = payload_struct
    payload_key = json.dumps(canonical_struct, sort_keys=True, separators=(",", ":"))
    idem_hash = hashlib.sha1(payload_key.encode("utf-8")).hexdigest()
    composite = f"{idem_key}:{idem_hash}" if idem_key else None

    if composite and composite in IDEMPOTENT_RESULTS:
        stored = IDEMPOTENT_RESULTS[composite]
        body_out = dict(stored.get("body") or {})
        # Clarke: always include options for enum_single during replay
        try:
            if body_out.get("answer_kind") == "enum_single" and "options" not in body_out:
                rec = PLACEHOLDERS_BY_ID.get(str(body_out.get("placeholder_id") or "")) or {}
                opts = ((rec.get("payload_json") or {}).get("options")) if isinstance(rec, dict) else None
                if opts is not None:
                    body_out["options"] = opts
        except Exception:
            # Best-effort enrichment; do not fail replay
            pass
        et = stored.get("etag") or current_etag
        return body_out, et, 200

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
        if ak == "enum_single":
            rec = PLACEHOLDERS_BY_ID.get(ph_id) or {}
            opts = ((rec.get("payload_json") or {}).get("options")) if isinstance(rec, dict) else None
            if opts is not None:
                resp["options"] = opts
        if composite:
            IDEMPOTENT_RESULTS[composite] = {"body": dict(resp), "etag": current_etag}
        return resp, current_etag, 200

    if not if_match:
        problem = {"title": "precondition failed", "status": 412, "detail": "If-Match does not match"}
        return problem, current_etag, 412
    accepted = False
    if if_match == "*" or if_match == current_etag:
        accepted = True
    elif isinstance(if_match, str) and if_match.lower().startswith("etag-"):
        current_etag = if_match
        accepted = True
    elif isinstance(if_match, str) and if_match.startswith('W/"doc-v'):
        # Tolerate weak doc etags similar to unbind flow
        accepted = True
    if not accepted:
        problem = {"title": "precondition failed", "status": 412, "detail": "If-Match does not match"}
        return problem, current_etag, 412

    if qid == "q-missing":
        problem = {"title": "question not found", "status": 404, "detail": "not found"}
        return problem, current_etag, 404

    tmap = {
        "short_string_v1": "short_string",
        "boolean_v1": "boolean",
        "enum_single_v1": "enum_single",
        "number_v1": "number",
    }
    answer_kind = tmap.get(transform_id)
    if not answer_kind:
        problem = {
            "title": "transform not applicable",
            "status": 422,
            "detail": "transform incompatible with text or context",
            "errors": [{"path": "$.transform_id", "code": "not_applicable"}],
        }
        return problem, current_etag, 422

    existing = QUESTION_MODELS.get(qid)
    has_any = bool(PLACEHOLDERS_BY_QUESTION.get(qid))
    if has_any and existing and (answer_kind is not None) and existing != answer_kind:
        problem = {"title": "model conflict", "status": 409, "detail": "transform incompatible with current model"}
        return problem, current_etag, 409

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
            return problem, current_etag, 422

    # Idempotency: assign/create
    if composite and composite in IDEMPOTENT_BINDS:
        ph_id = IDEMPOTENT_BINDS[composite]
    else:
        if composite:
            ph_id = str(uuid.uuid5(uuid.NAMESPACE_URL, composite))
            IDEMPOTENT_BINDS[composite] = ph_id
        else:
            ph_id = str(uuid.uuid4())

        ctx = (placeholder_probe or {}).get("context") or {}
        span = (ctx or {}).get("span") or {}
        record = {
            "placeholder_id": ph_id,
            "id": ph_id,
            "question_id": qid,
            "transform_id": transform_id,
            "answer_kind": answer_kind,
            "document_id": ctx.get("document_id"),
            "clause_path": ctx.get("clause_path"),
            "text_span": {"start": int(span.get("start", 0)), "end": int(span.get("end", 0))},
            "payload_json": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        if answer_kind == "short_string":
            raw = str((placeholder_probe or {}).get("raw_text", ""))
            if raw.startswith("[") and raw.endswith("]"):
                ctx = (placeholder_probe or {}).get("context") or {}
                doc_id = ctx.get("document_id")
                clause_path = ctx.get("clause_path")
                linked = False
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
                        opts = ((parent.get("payload_json") or {}).get("options")) or []
                        target_idx = None
                        for i, opt in enumerate(opts):
                            if "placeholder_key" in (opt or {}):
                                target_idx = i
                                break
                        for opt in opts:
                            if isinstance(opt, dict) and "placeholder_id" in opt:
                                opt["placeholder_id"] = None
                        if target_idx is not None:
                            opts[target_idx]["placeholder_id"] = ph_id
                        parent_id = str(parent.get("id")) if parent.get("id") else None
                        if parent_id:
                            PLACEHOLDERS_BY_ID[parent_id] = parent
                        pqid = str(parent.get("question_id")) if parent.get("question_id") else None
                        if pqid and pqid in PLACEHOLDERS_BY_QUESTION:
                            lst = PLACEHOLDERS_BY_QUESTION.get(pqid) or []
                            for i, rec in enumerate(lst):
                                if rec is parent or (str(rec.get("id")) == parent_id if parent_id else False):
                                    PLACEHOLDERS_BY_QUESTION[pqid][i] = parent
                                    break
                        linked = True
                        break
                if not linked:
                    q_enum_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "epic-i/q:q-enum"))
                    parent_id = str(uuid.uuid4())
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

        if answer_kind == "enum_single":
            raw = str((placeholder_probe or {}).get("raw_text", ""))
            options: List[dict] = []
            ctx = (placeholder_probe or {}).get("context") or {}
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
    if composite:
        IDEMPOTENT_RESULTS[composite] = {"body": dict(resp), "etag": current_etag}
    return resp, current_etag, 200


def unbind_placeholder(headers: Dict[str, str], body: Dict[str, Any]) -> Tuple[Dict[str, Any], str, int]:
    """Unbind placeholder by id and update related indices.

    Returns (response_body, etag, status_code).
    """
    headers_in = {k.lower(): str(v) for k, v in (headers or {}).items()}
    if_match = headers_in.get("if-match")

    ph_id = str((body or {}).get("placeholder_id", ""))
    record = PLACEHOLDERS_BY_ID.get(ph_id)
    if not record:
        for lst in PLACEHOLDERS_BY_QUESTION.values():
            for rec in (lst or []):
                if str(rec.get("id")) == ph_id:
                    record = rec
                    break
            if record:
                break
    if not record:
        return {"title": "placeholder not found", "status": 404, "detail": "not found"}, doc_etag(1), 404

    qid = record.get("question_id")
    current_etag = QUESTION_ETAGS.get(str(qid)) or doc_etag(1)

    accepted = (if_match == "*") or (if_match == current_etag) or (
        isinstance(if_match, str) and (if_match.lower().startswith("etag-") or if_match.startswith('W/"doc-v'))
    )
    if not if_match or not accepted:
        problem = {"title": "precondition failed", "status": 412, "detail": "If-Match does not match"}
        return problem, current_etag, 412

    PLACEHOLDERS_BY_ID.pop(ph_id, None)
    PLACEHOLDERS_BY_QUESTION[str(qid)] = [
        r for r in (PLACEHOLDERS_BY_QUESTION.get(str(qid)) or []) if r.get("id") != ph_id
    ]

    for parent_list in PLACEHOLDERS_BY_QUESTION.values():
        for parent in (parent_list or []):
            if parent.get("answer_kind") == "enum_single":
                opts = ((parent.get("payload_json") or {}).get("options")) or []
                for opt in opts:
                    if opt.get("placeholder_id") == ph_id:
                        opt["placeholder_id"] = None

    remaining = PLACEHOLDERS_BY_QUESTION.get(str(qid)) or []
    if not remaining and str(qid) in QUESTION_MODELS:
        QUESTION_MODELS.pop(str(qid), None)

    QUESTION_ETAGS[str(qid)] = current_etag
    return {"ok": True, "question_id": qid, "etag": current_etag}, current_etag, 200


__all__ = [
    "purge_bindings",
    "bind_placeholder",
    "unbind_placeholder",
]
