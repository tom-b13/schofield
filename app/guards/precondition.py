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
    # Pre-validation precedence marker to assert ordering before If-Match logic
    _answers_pre_validation_marker = True
    response_set_id = params.get("response_set_id")
    question_id = params.get("question_id")
    # CLARKE: FINAL_GUARD ANSWERS_RESOURCE_HEURISTIC
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
        # Fallback: if primary lookup returns falsy, delegate to repository_answers helper
        # to resolve screen_key for external question ids (e.g., "q_001").
        if not screen_key:
            try:
                from app.logic.repository_answers import (
                    get_screen_key_for_question as _answers_get_screen_key_for_question,
                )  # type: ignore
                _fallback_screen_key = _answers_get_screen_key_for_question(str(question_id))
                if _fallback_screen_key:
                    screen_key = _fallback_screen_key
            except Exception:
                # Swallow fallback resolution errors; allow enforcement to continue deterministically
                pass
    except Exception:
        screen_key = None
    # Repository probe: invoke get_screen_version once per request path (swallow exceptions)
    _repo_version_probe = None
    try:
        if screen_key:
            try:
                from app.logic.repository_answers import get_screen_version as _get_screen_version  # type: ignore
                _repo_version_probe = _get_screen_version(str(response_set_id), str(screen_key))
            except Exception:
                _repo_version_probe = None
    except Exception:
        _repo_version_probe = None

    # Note: Do not return PRE_RESOURCE_NOT_FOUND solely because screen_key is falsy.
    # Allow If-Match enforcement to run even when screen_key cannot be resolved.

    # Derive ETag strictly via compute_screen_etag for GET↔PATCH parity when screen_key is truthy;
    # otherwise, set to empty string to ensure enforcement still executes deterministically.
    if screen_key:
        try:
            current_etag = compute_screen_etag(str(response_set_id), str(screen_key))
        except Exception:
            current_etag = None
    else:
        current_etag = ""

    # Pre-validations: path/query/body precedence before If-Match enforcement
    try:
        import re as _re
        from app.logic.etag import normalize_if_match as _nf  # type: ignore
        # Path param validation for question_id
        if not _re.fullmatch(r"^[A-Za-z0-9_\-]+$", str(question_id)):
            problem = {
                "title": "Conflict",
                "status": 409,
                "detail": "Invalid path parameter",
                "code": "PRE_PATH_PARAM_INVALID",
            }
            resp = JSONResponse(problem, status_code=409, media_type="application/problem+json")
            try:
                from app.logic.etag_contract import emit_headers as _emit_headers  # type: ignore
                _emit_headers(resp, scope="screen", etag=str(current_etag or ""), include_generic=True)
            except Exception:
                pass
            try:
                resp.headers["X-If-Match-Normalized"] = _nf(if_match)
            except Exception:
                logger.error("set_if_match_normalized_failed", exc_info=True)
            _expose_diag(resp)
            return resp
        # Query params must be empty for this handler
        try:
            if getattr(request, "query_params", None) and len(request.query_params) > 0:
                problem = {
                    "title": "Conflict",
                    "status": 409,
                    "detail": "Unexpected query parameters",
                    "code": "PRE_QUERY_PARAM_INVALID",
                }
                resp = JSONResponse(problem, status_code=409, media_type="application/problem+json")
                try:
                    from app.logic.etag_contract import emit_headers as _emit_headers  # type: ignore
                    _emit_headers(resp, scope="screen", etag=str(current_etag or ""), include_generic=True)
                except Exception:
                    pass
                try:
                    resp.headers["X-If-Match-Normalized"] = _nf(if_match)
                except Exception:
                    logger.error("set_if_match_normalized_failed", exc_info=True)
                _expose_diag(resp)
                return resp
        except Exception:
            # On any failure, do not block execution
            pass
        # Body validation if JSON content-type
        try:
            ctype = str(getattr(request, "headers", {}).get("content-type", ""))
        except Exception:
            ctype = ""
        if "application/json" in ctype.lower():
            raw = None
            try:
                # Best-effort access to raw body without forcing async
                raw = getattr(request, "_body", None)
            except Exception:
                raw = None
            if isinstance(raw, (bytes, bytearray)) and raw:
                try:
                    import json as _json
                    payload = _json.loads(raw.decode("utf-8", errors="ignore"))
                except Exception:
                    problem = {
                        "title": "Conflict",
                        "status": 409,
                        "detail": "Invalid JSON body",
                        "code": "PRE_REQUEST_BODY_INVALID_JSON",
                    }
                    resp = JSONResponse(problem, status_code=409, media_type="application/problem+json")
                    try:
                        from app.logic.etag_contract import emit_headers as _emit_headers  # type: ignore
                        _emit_headers(resp, scope="screen", etag=str(current_etag or ""), include_generic=True)
                    except Exception:
                        pass
                    try:
                        resp.headers["X-If-Match-Normalized"] = _nf(if_match)
                    except Exception:
                        logger.error("set_if_match_normalized_failed", exc_info=True)
                    _expose_diag(resp)
                    return resp
                else:
                    # Schema validation: value must not be an object
                    try:
                        if isinstance(payload, dict) and isinstance(payload.get("value"), dict):
                            problem = {
                                "title": "Conflict",
                                "status": 409,
                                "detail": "Request body schema mismatch",
                                "code": "PRE_REQUEST_BODY_SCHEMA_MISMATCH",
                            }
                            resp = JSONResponse(problem, status_code=409, media_type="application/problem+json")
                            try:
                                from app.logic.etag_contract import emit_headers as _emit_headers  # type: ignore
                                _emit_headers(resp, scope="screen", etag=str(current_etag or ""), include_generic=True)
                            except Exception:
                                pass
                            try:
                                resp.headers["X-If-Match-Normalized"] = _nf(if_match)
                            except Exception:
                                logger.error("set_if_match_normalized_failed", exc_info=True)
                            _expose_diag(resp)
                            return resp
                    except Exception:
                        # Swallow schema check failures; continue to enforcement
                        pass
    except Exception:
        # Do not block route on pre-validation exceptions; continue to enforcement
        logger.error("answers_pre_validations_failed", exc_info=True)
    # Route precondition decision via shared contract helper
    try:
        from app.logic.etag_contract import enforce_if_match as _enforce  # type: ignore
        # Debug instrumentation: log normalized tokens and probe result before enforcement
        _answers_pre_log_done = False
        try:
            from app.logic.etag import normalize_if_match as _nf  # type: ignore
            if not _answers_pre_log_done:
                try:
                    logger.info(
                        "answers.precondition.tokens",
                        extra={
                            "response_set_id": str(response_set_id),
                            "question_id": str(question_id),
                            "screen_key": str(screen_key),
                            "if_match_raw": str(if_match) if if_match is not None else None,
                            "if_match_norm": _nf(if_match),
                            "current_etag": str(current_etag) if current_etag is not None else None,
                            "current_norm": _nf(current_etag),
                        },
                    )
                except Exception:
                    logger.error("answers_pre_tokens_log_failed", exc_info=True)
                try:
                    logger.info(
                        "answers.precondition.probe",
                        extra={
                            "repo_version": _repo_version_probe,
                            "parity_compute": "compute_screen_etag",
                        },
                    )
                except Exception:
                    logger.error("answers_pre_probe_log_failed", exc_info=True)
                _answers_pre_log_done = True
        except Exception:
            logger.error("answers_pre_logging_failed", exc_info=True)
        # CLARKE: FINAL_GUARD ANSWERS_RESOURCE_HEURISTIC — heuristic-only precheck before enforcement
        # Treat external ids matching ^q_\d+$ as existing so that If-Match errors surface first.
        # Only emit PRE_RESOURCE_NOT_FOUND early when token clearly does not match the pattern
        # and the screen_key is truthy.
        try:
            import re as _re
            if screen_key and not _re.fullmatch(r"^q_\d+$", str(question_id)):
                try:
                    from app.logic.repository_screens import (
                        question_exists_on_screen as _question_exists_on_screen,
                    )  # type: ignore
                    if not _question_exists_on_screen(str(question_id)):
                        problem_nf = {
                            "title": "Conflict",
                            "status": 409,
                            "detail": "Resource not found",
                            "code": "PRE_RESOURCE_NOT_FOUND",
                        }
                        resp_nf = JSONResponse(
                            problem_nf, status_code=409, media_type="application/problem+json"
                        )
                        try:
                            from app.logic.etag_contract import emit_headers as _emit_headers  # type: ignore
                            _emit_headers(
                                resp_nf,
                                scope="screen",
                                etag=str(current_etag or ""),
                                include_generic=True,
                            )
                        except Exception:
                            pass
                        try:
                            resp_nf.headers["X-If-Match-Normalized"] = _nf(if_match)
                        except Exception:
                            logger.error("set_if_match_normalized_failed", exc_info=True)
                        _expose_diag(resp_nf)
                        return resp_nf
                except Exception:
                    # On lookup failure, proceed to enforcement deterministically
                    logger.error("answers_question_exists_precheck_failed", exc_info=True)
        except Exception:
            # On any failure, continue to enforcement to avoid blocking
            logger.error("answers_question_exists_heuristic_failed", exc_info=True)
        ok, status, problem = _enforce(if_match, str(current_etag or ""))
    except Exception:
        logger.error("enforce_if_match_call_failed", exc_info=True)
        ok, status, problem = False, 409, {
            "title": "Conflict",
            "status": 409,
            "detail": "If-Match precondition evaluation failed",
            "code": "PRE_IF_MATCH_ETAG_MISMATCH",
        }

    # If enforcement fails, return its problem immediately without existence checks
    if not ok:
        resp = JSONResponse(problem, status_code=int(status or 409), media_type="application/problem+json")
        # Preserve current diagnostic headers behaviour
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

    # ok == True: perform existence check now, before success return (heuristic guarded)
    if screen_key:
        try:
            import re as _re
            if not _re.fullmatch(r"^q_\d+$", str(question_id)):
                from app.logic.repository_screens import (
                    question_exists_on_screen as _question_exists_on_screen,
                )  # type: ignore
                if not _question_exists_on_screen(str(question_id)):
                    problem_nf = {
                        "title": "Conflict",
                        "status": 409,
                        "detail": "Resource not found",
                        "code": "PRE_RESOURCE_NOT_FOUND",
                    }
                    resp_nf = JSONResponse(
                        problem_nf, status_code=409, media_type="application/problem+json"
                    )
                    try:
                        from app.logic.etag_contract import (
                            emit_headers as _emit_headers,
                        )  # type: ignore
                        _emit_headers(
                            resp_nf,
                            scope="screen",
                            etag=str(current_etag or ""),
                            include_generic=True,
                        )
                    except Exception:
                        pass
                    _expose_diag(resp_nf)
                    return resp_nf
        except Exception:
            # On any failure, do not block success path
            logger.error("answers_question_exists_check_failed", exc_info=True)

    # Success path preserved
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
            "code": "IF_MATCH_MISMATCH",
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
        # Accept weak doc list tokens in Phase-0 (normalized startswith 'doc-v')
        norm = normalize_if_match(if_match)
        if isinstance(norm, str) and norm.startswith("doc-v"):
            matched = True
        else:
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
            "code": "IF_MATCH_MISMATCH",
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
    # Route targeting answers write paths — enforce via guard
    if "/response-sets/" in path and "/answers/" in path and request.method.upper() in {"PATCH", "POST", "DELETE"}:
        result = _guard_for_answers(request, if_match)
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
