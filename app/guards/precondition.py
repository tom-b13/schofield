"""Precondition guard dependency for If-Match enforcement (Phase-0).

Enforces presence and equality of the If-Match header for specific write
routes using the shared ETag compare utility. Routes that do not require
If-Match are ignored by this guard to keep behaviour scoped for Phase-0.
"""

from __future__ import annotations

from typing import Annotated, Optional
import logging

from fastapi import Header, Request, HTTPException
from fastapi.responses import JSONResponse


logger = logging.getLogger(__name__)

# Architectural compliance: do not import private members from app.logic.etag


def _expose_diag(resp: JSONResponse) -> None:
    """Ensure diagnostic headers are exposed via CORS.

    Includes diagnostic and domain/generic ETag headers for completeness.
    """
    try:
        names = [
            "X-List-ETag",
            "X-If-Match-Normalized",
            "ETag",
            "Screen-ETag",
            "Document-ETag",
            "Question-ETag",
            "Questionnaire-ETag",
        ]
        resp.headers["Access-Control-Expose-Headers"] = ", ".join(names)
    except Exception:
        logger.error("expose_diag_failed", exc_info=True)


def _guard_for_answers(request: Request, if_match: str | None) -> Optional[JSONResponse]:
    params = getattr(request, "path_params", {}) or {}
    response_set_id = params.get("response_set_id")
    question_id = params.get("question_id")
    if not (response_set_id and question_id):
        return None
    # Local imports to avoid import-time DB driver errors
    try:
        from app.logic.repository_screens import get_screen_key_for_question  # type: ignore
        from app.logic.etag import (
            compute_screen_etag,
            compare_etag,
            normalize_if_match,
        )  # type: ignore
    except Exception:
        # If imports fail, emit existing problem shapes rather than raising
        # Local normaliser fallback to include diagnostics header
        def _norm_token(v: str | None) -> str:
            try:
                from app.logic.etag import normalize_if_match as _nf  # type: ignore
                return _nf(v)
            except Exception:
                s = (v or "").strip()
                if not s:
                    return ""
                if s == "*":
                    return s
                while len(s) >= 2 and s[:2].upper() == "W/":
                    s = s[2:].strip()
                if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
                    s = s[1:-1].strip()
                return s.lower()
        if not if_match or not str(if_match).strip():
            problem = {
                "title": "Precondition Required",
                "status": 428,
                "detail": "If-Match header is required for this operation",
                "code": "PRE_IF_MATCH_MISSING",
            }
            resp = JSONResponse(problem, status_code=428, media_type="application/problem+json")
            resp.headers["Access-Control-Expose-Headers"] = (
                "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
            )
            try:
                resp.headers["X-If-Match-Normalized"] = _norm_token(if_match)
            except Exception:
                logger.error("set_if_match_normalized_failed", exc_info=True)
            _expose_diag(resp)
            return resp
        problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "If-Match does not match current ETag",
            "code": "PRE_IF_MATCH_ETAG_MISMATCH",
        }
        resp = JSONResponse(problem, status_code=409, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        try:
            resp.headers["X-If-Match-Normalized"] = _norm_token(if_match)
        except Exception:
            logger.error("set_if_match_normalized_failed", exc_info=True)
        _expose_diag(resp)
        return resp
    # Resolve screen_key and current screen ETag
    try:
        screen_key = get_screen_key_for_question(str(question_id))
    except Exception:
        screen_key = None
    if not screen_key:
        # Let the handler surface 404s consistently
        return None
    # Prefer parity with GET by deriving ETag from assembled screen_view
    try:
        # Prefer pre-assembled screen_view.etag parity with GET
        from app.logic.screen_builder import assemble_screen_view  # type: ignore
        sv = assemble_screen_view(str(response_set_id), str(screen_key))
        current_etag = sv.get("etag") or compute_screen_etag(str(response_set_id), str(screen_key))
    except Exception:
        try:
            current_etag = compute_screen_etag(str(response_set_id), str(screen_key))
        except Exception:
            current_etag = None
    # Presence required
    if not if_match or not str(if_match).strip():
        problem = {
            "title": "Precondition Required",
            "status": 428,
            "detail": "If-Match header is required for this operation",
            "code": "PRE_IF_MATCH_MISSING",
        }
        resp = JSONResponse(problem, status_code=428, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        try:
            from app.logic.etag import normalize_if_match as _nf  # type: ignore
            resp.headers["X-If-Match-Normalized"] = _nf(if_match)
        except Exception:
            logger.error("set_if_match_normalized_failed", exc_info=True)
        _expose_diag(resp)
        try:
            logger.info(
                "etag.enforce matched=%s resource=%s route=%s if_match_norm=%s current=%s",
                False,
                "screen",
                str(request.url.path),
                normalize_if_match(if_match),
                str(current_etag) if current_etag is not None else None,
            )
        except Exception:
            logger.error("log_etag_enforce_failed", exc_info=True)
        return resp
    try:
        matched = compare_etag(current_etag, str(if_match))
    except Exception:
        matched = False
    try:
        logger.info(
            "etag.enforce matched=%s resource=%s route=%s if_match_norm=%s current=%s",
            matched,
            "screen",
            str(request.url.path),
            normalize_if_match(if_match),
            str(current_etag) if current_etag is not None else None,
        )
    except Exception:
        logger.error("log_etag_enforce_failed", exc_info=True)
    if not matched:
        # Conflict semantics for autosave answers
        problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "If-Match does not match current ETag",
            "code": "PRE_IF_MATCH_ETAG_MISMATCH",
        }
        resp = JSONResponse(problem, status_code=409, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        try:
            from app.logic.etag import normalize_if_match as _nf  # type: ignore
            resp.headers["X-If-Match-Normalized"] = _nf(if_match)
        except Exception:
            logger.error("set_if_match_normalized_failed", exc_info=True)
        _expose_diag(resp)
        return resp
    return None


def _guard_for_doc_content(request: Request, if_match: str | None) -> Optional[JSONResponse]:
    params = getattr(request, "path_params", {}) or {}
    document_id = params.get("document_id")
    if not document_id:
        return None
    # Local imports
    try:
        from app.logic.repository_documents import get_document as repo_get_document  # type: ignore
        from app.logic.inmemory_state import DOCUMENTS_STORE  # type: ignore
        from app.logic.etag import doc_etag, compare_etag  # type: ignore
    except Exception:
        if not if_match or not str(if_match).strip():
            problem = {
                "title": "Precondition Required",
                "status": 428,
                "detail": "If-Match header is required",
                "code": "PRE_IF_MATCH_MISSING_DOCUMENT",
            }
            resp = JSONResponse(problem, status_code=428, media_type="application/problem+json")
            resp.headers["Access-Control-Expose-Headers"] = (
                "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
            )
            _expose_diag(resp)
            return resp
        problem = {
            "title": "Precondition Failed",
            "status": 412,
            "detail": "ETag mismatch",
            "code": "RUN_DOC_ETAG_MISMATCH",
        }
        resp = JSONResponse(problem, status_code=412, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        _expose_diag(resp)
        return resp
    try:
        doc = repo_get_document(str(document_id), store=DOCUMENTS_STORE)  # type: ignore[arg-type]
    except Exception:
        doc = None
    if not doc:
        return None
    try:
        current_etag = doc_etag(int(doc.get("version", 0)))
    except Exception:
        current_etag = None
    if not if_match or not str(if_match).strip():
        problem = {
            "title": "Precondition Required",
            "status": 428,
            "detail": "If-Match header is required",
            "code": "PRE_IF_MATCH_MISSING_DOCUMENT",
        }
        resp = JSONResponse(problem, status_code=428, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        _expose_diag(resp)
        try:
            logger.info(
                "etag.enforce matched=%s resource=%s route=%s",
                False,
                "document",
                str(request.url.path),
            )
        except Exception:
            logger.error("log_etag_enforce_failed", exc_info=True)
        return resp
    try:
        matched = compare_etag(current_etag, str(if_match))
    except Exception:
        matched = False
    try:
        logger.info(
            "etag.enforce matched=%s resource=%s route=%s",
            matched,
            "document",
            str(request.url.path),
        )
    except Exception:
        logger.error("log_etag_enforce_failed", exc_info=True)
    if not matched:
        problem = {
            "title": "Precondition Failed",
            "status": 412,
            "detail": "ETag mismatch",
            "code": "RUN_DOC_ETAG_MISMATCH",
        }
        resp = JSONResponse(problem, status_code=412, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        _expose_diag(resp)
        return resp
    return None


def _guard_for_doc_reorder(request: Request, if_match: str | None) -> Optional[JSONResponse]:
    # Only enforce on explicit reorder paths
    if "reorder" not in str(request.url.path) and not str(request.url.path).endswith("/documents/order"):
        return None
    # Local imports
    try:
        from app.logic.inmemory_state import DOCUMENTS_STORE  # type: ignore
        from app.logic.etag import (
            compute_document_list_etag,
            compare_etag,
            normalize_if_match,
        )  # type: ignore
        from app.logic.header_emitter import emit_etag_headers  # type: ignore
    except Exception:
        if not if_match or not str(if_match).strip():
            problem = {
                "title": "Precondition Required",
                "status": 428,
                "detail": "If-Match header is required",
                "code": "PRE_IF_MATCH_MISSING_LIST",
            }
            resp = JSONResponse(problem, status_code=428, media_type="application/problem+json")
            resp.headers["Access-Control-Expose-Headers"] = (
                "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
            )
            _expose_diag(resp)
            return resp
        problem = {
            "title": "Precondition Failed",
            "status": 412,
            "detail": "list ETag mismatch",
            "code": "RUN_LIST_ETAG_MISMATCH",
        }
        resp = JSONResponse(problem, status_code=412, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        _expose_diag(resp)
        return resp
    try:
        current = compute_document_list_etag(list(DOCUMENTS_STORE.values()))
    except Exception:
        current = None
    # Use shared normaliser from app.logic.etag for diagnostics
    if not if_match or not str(if_match).strip():
        problem = {
            "title": "Precondition Required",
            "status": 428,
            "detail": "If-Match header is required",
            "code": "PRE_IF_MATCH_MISSING_LIST",
        }
        resp = JSONResponse(problem, status_code=428, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        try:
            logger.info(
                "etag.enforce matched=%s resource=%s route=%s",
                False,
                "document_list",
                str(request.url.path),
            )
        except Exception:
            logger.error("log_etag_enforce_failed", exc_info=True)
        _expose_diag(resp)
        return resp
    try:
        matched = compare_etag(current, str(if_match))
    except Exception:
        matched = False
    try:
        logger.info(
            "etag.enforce",
            matched=matched,
            resource="document_list",
            route=str(request.url.path),
            if_match_raw=str(if_match) if if_match is not None else None,
            if_match_norm=normalize_if_match(if_match),
            current=str(current) if current is not None else None,
        )
    except Exception:
        logger.error("log_etag_enforce_failed", exc_info=True)
    if not matched:
        problem = {
            "title": "Precondition Failed",
            "status": 412,
            "detail": "list ETag mismatch",
            "code": "RUN_LIST_ETAG_MISMATCH",
            "current_list_etag": current,
        }
        resp = JSONResponse(problem, status_code=412, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        # Emit domain and generic ETag headers with current list token
        try:
            emit_etag_headers(resp, scope="document", token=str(current), include_generic=True)
        except Exception:
            logger.error("emit_etag_headers_failed", exc_info=True)
        # Preserve diagnostics via headers
        try:
            resp.headers["X-List-ETag"] = str(current)
        except Exception:
            logger.error("emit_list_etag_failed", exc_info=True)
        # Include normalized If-Match for diagnostics per Clarke
        try:
            resp.headers["X-If-Match-Normalized"] = normalize_if_match(if_match)
        except Exception:
            logger.error("set_if_match_normalized_failed", exc_info=True)
        _expose_diag(resp)
        # Short-circuit request by raising with headers preserved
        raise HTTPException(status_code=412, detail=problem, headers=dict(resp.headers))
    return None


def precondition_guard(
    request: Request,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):  # pragma: no cover - enforced by architectural tests
    """FastAPI dependency that enforces If-Match for specific write routes.

    Returns a JSONResponse on failure; returns None on success (continue).
    """
    path = str(request.url.path)
    # Route targeting answers autosave — Phase-0: no-op to preserve handler semantics
    if "/response-sets/" in path and "/answers/" in path and request.method.upper() in {"PATCH", "POST", "DELETE"}:
        # Clarke directive: in Phase-0 do not enforce here; handler performs If-Match checks
        return None
    # Document content upload
    if "/documents/" in path and path.endswith("/content") and request.method.upper() == "PUT":
        result = _guard_for_doc_content(request, if_match)
        if result is not None:
            try:
                import json as _json
                detail_obj = None
                body_bytes = getattr(result, "body", None)
                if isinstance(body_bytes, (bytes, bytearray)):
                    try:
                        detail_obj = _json.loads(body_bytes.decode("utf-8", errors="ignore"))
                    except Exception:
                        detail_obj = None
                if not isinstance(detail_obj, dict):
                    detail_obj = {"title": "Error", "status": int(getattr(result, "status_code", 500) or 500)}
            except Exception:
                detail_obj = {"title": "Error", "status": int(getattr(result, "status_code", 500) or 500)}
            _hdrs = dict(result.headers)
            try:
                for k in list(_hdrs.keys()):
                    if str(k).lower() == "content-length":
                        _hdrs.pop(k, None)
            except Exception:
                logger.error("strip_content_length_failed", exc_info=True)
            raise HTTPException(status_code=result.status_code, detail=detail_obj, headers=_hdrs)
        return None
    # Document reorder
    if request.method.upper() == "PUT" and (path.endswith("/documents/order") or ("/documents/reorder" in path)):
        result = _guard_for_doc_reorder(request, if_match)
        if result is not None:
            try:
                import json as _json
                detail_obj = None
                body_bytes = getattr(result, "body", None)
                if isinstance(body_bytes, (bytes, bytearray)):
                    try:
                        detail_obj = _json.loads(body_bytes.decode("utf-8", errors="ignore"))
                    except Exception:
                        detail_obj = None
                if not isinstance(detail_obj, dict):
                    detail_obj = {"title": "Error", "status": int(getattr(result, "status_code", 500) or 500)}
            except Exception:
                detail_obj = {"title": "Error", "status": int(getattr(result, "status_code", 500) or 500)}
            _hdrs = dict(result.headers)
            try:
                for k in list(_hdrs.keys()):
                    if str(k).lower() == "content-length":
                        _hdrs.pop(k, None)
            except Exception:
                logger.error("strip_content_length_failed", exc_info=True)
            raise HTTPException(status_code=result.status_code, detail=detail_obj, headers=_hdrs)
        return None
    # Phase-0 scope: ignore other routes (no-op)
    return None


__all__ = ["precondition_guard"]

# Duplicate If-Match normaliser removed; rely on route/header emitter diagnostics
