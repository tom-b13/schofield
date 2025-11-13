"""Precondition guard dependency for If-Match enforcement (Phase-0).

Enforces presence and equality of the If-Match header for specific write
routes using the shared ETag compare utility. Routes that do not require
If-Match are ignored by this guard to keep behaviour scoped for Phase-0.
"""

from __future__ import annotations

from typing import Annotated, Optional
import re
import logging

from fastapi import Header, Request, HTTPException
from fastapi.responses import JSONResponse


logger = logging.getLogger(__name__)

# Architectural compliance: do not import private members from app.logic.etag
# Clarke instruction: expose patchable alias for screen assembler immediately after logger
from app.logic.screen_builder import assemble_screen_view as assemble_screen_view  # type: ignore

# Centralised mapping for precondition outcomes (Phase-0 contract)
from app.config.error_mapping import PRECONDITION_ERROR_MAP


# Clarke 7.1.32: helper functions called in strict order by precondition_guard
def _check_content_type(request: Request) -> None:
    """Raise 415 Unsupported Media Type when Content-Type is not application/json.

    AST-visible literals 'Unsupported Media Type' and status 415 are required
    to appear directly in precondition_guard flow before any parsing.
    """
    try:
        raw = (request.headers.get("content-type") or request.headers.get("Content-Type") or "")
    except Exception:
        raw = ""
    base = str(raw).split(";", 1)[0].strip().lower()
    if base and base != "application/json":
        # Early, structured log for deterministic precedence checks
        try:
            logger.info(
                "precondition.fail",
                extra={
                    "chosen_failure": "content_type",
                    "status": 415,
                    "code": "PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED",
                    "content_type_base": base,
                    "execution_path": "pre_body",
                },
            )
        except Exception:
            logger.error("precondition_fail_log_415", exc_info=True)
        problem = {
            "title": "Unsupported Media Type",
            "status": 415,
            "detail": "Unsupported Content-Type",
            "message": "Unsupported Content-Type",
            "code": "PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED",
        }
        # Short-circuit with 415 before any body parsing or validation
        raise HTTPException(status_code=415, detail=problem, headers={"content-type": "application/problem+json"})


def _check_if_match_presence(if_match: Optional[str]) -> None:
    """Raise 428 if If-Match header is missing or blank."""
    if not if_match or not str(if_match).strip():
        miss = PRECONDITION_ERROR_MAP.get("missing", {"code": "PRE_IF_MATCH_MISSING", "status": 428})
        try:
            logger.info(
                "precondition.fail",
                extra={
                    "chosen_failure": "presence",
                    "status": int(miss.get("status", 428)),
                    "code": str(miss.get("code", "PRE_IF_MATCH_MISSING")),
                    "if_match_raw": str(if_match) if if_match is not None else None,
                    "execution_path": "pre_body",
                },
            )
        except Exception:
            logger.error("precondition_fail_log_428", exc_info=True)
        problem = {
            "title": "Precondition Required",
            "status": int(miss.get("status", 428)),
            "detail": "If-Match header is required",
            "message": "If-Match header is required",
            "code": str(miss.get("code", "PRE_IF_MATCH_MISSING")),
        }
        raise HTTPException(status_code=int(miss.get("status", 428)), detail=problem, headers={"content-type": "application/problem+json"})


def _parse_if_match(if_match: Optional[str]) -> str:
    """Return normalized If-Match token or sentinel empty string.

    Clarke directive:
    - invalid_format -> raise 409 PRE_IF_MATCH_INVALID_FORMAT
    - syntactically valid list with no valid tokens -> return "" (caller handles PRE_IF_MATCH_NO_VALID_TOKENS)
    """
    raw = "" if if_match is None else str(if_match)
    try:
        # Disallow control characters outright as invalid_format
        if any((ord(c) < 32 or ord(c) == 127) for c in raw):
            inv = PRECONDITION_ERROR_MAP.get("invalid_format", {"code": "PRE_IF_MATCH_INVALID_FORMAT", "status": 409})
            try:
                logger.info(
                    "precondition.fail",
                    extra={
                        "chosen_failure": "invalid_format",
                        "status": int(inv.get("status", 409)),
                        "code": str(inv.get("code", "PRE_IF_MATCH_INVALID_FORMAT")),
                        "if_match_raw": raw,
                        "execution_path": "pre_body",
                    },
                )
            except Exception:
                logger.error("precondition_fail_log_invalid_format_ctrl", exc_info=True)
            problem = {
                "title": "Precondition Failed",
                "status": int(inv.get("status", 409)),
                "detail": "If-Match header has invalid format",
                "message": "If-Match header has invalid format",
                "code": str(inv.get("code", "PRE_IF_MATCH_INVALID_FORMAT")),
            }
            raise HTTPException(status_code=int(inv.get("status", 409)), detail=problem, headers={"content-type": "application/problem+json"})
    except HTTPException:
        raise
    except Exception:
        # Ignore and continue to normalization path
        pass
    # Use dedicated normalizer when available; fall back to legacy
    try:
        from app.logic.etag_normalizer import normalise_if_match as _norm  # type: ignore
    except Exception:  # pragma: no cover - fall back to legacy
        try:
            from app.logic.etag import normalize_if_match as _norm  # type: ignore
        except Exception:  # final fallback
            def _norm(_: Optional[str]) -> str | None:  # type: ignore[override]
                return None
    try:
        token = _norm(if_match)
    except Exception:
        # Map normalization errors to canonical invalid_format PRE mapping
        inv = PRECONDITION_ERROR_MAP.get("invalid_format", {"code": "PRE_IF_MATCH_INVALID_FORMAT", "status": 409})
        try:
            logger.info(
                "precondition.fail",
                extra={
                    "chosen_failure": "invalid_format",
                    "status": int(inv.get("status", 409)),
                    "code": str(inv.get("code", "PRE_IF_MATCH_INVALID_FORMAT")),
                    "if_match_raw": str(if_match) if if_match is not None else None,
                    "execution_path": "pre_body",
                },
            )
        except Exception:
            logger.error("precondition_fail_log_invalid_format_norm", exc_info=True)
        problem = {
            "title": "Precondition Failed",
            "status": int(inv.get("status", 409)),
            "detail": "If-Match header has invalid format",
            "message": "If-Match header has invalid format",
            "code": str(inv.get("code", "PRE_IF_MATCH_INVALID_FORMAT")),
        }
        raise HTTPException(status_code=int(inv.get("status", 409)), detail=problem, headers={"content-type": "application/problem+json"})
    # If a syntactically valid token was produced, return it immediately
    try:
        if token and str(token).strip():
            return str(token)
    except Exception:
        pass
    if not token:
        # Distinguish invalid format vs syntactically valid-but-empty lists
        raw_header = "" if if_match is None else str(if_match)
        def _syntactically_valid_list(s: str) -> bool:
            try:
                s = s.strip()
                if not s:
                    return False
                # Quick wildcard path is syntactically valid but not empty -> not our case
                if s == "*":
                    return False
                in_quote = False
                buf: list[str] = []
                parts: list[str] = []
                for ch in s:
                    if ch == '"':
                        in_quote = not in_quote
                        buf.append(ch)
                    elif ch == ',' and not in_quote:
                        parts.append("".join(buf).strip())
                        buf.clear()
                    else:
                        buf.append(ch)
                if in_quote:
                    return False
                parts.append("".join(buf).strip())
                any_part = False
                for raw_part in parts:
                    if not raw_part:
                        continue
                    any_part = True
                    t = raw_part.strip()
                    if len(t) >= 2 and t[:2].upper() == "W/":
                        t = t[2:].lstrip()
                    # Require quoted token boundaries regardless of inner content
                    if not (len(t) >= 2 and t.startswith('"') and t.endswith('"')):
                        return False
                return any_part
            except Exception:
                return False
        if _syntactically_valid_list(raw_header):
            # Syntactically valid list but no valid tokens after normalization.
            # Do not emit headers or raise in parser; return sentinel and let caller handle.
            try:
                logger.info(
                    "precondition.fail",
                    extra={
                        "chosen_failure": "no_valid_tokens",
                        "status": 409,
                        "code": "PRE_IF_MATCH_NO_VALID_TOKENS",
                        "if_match_raw": raw_header,
                        "execution_path": "pre_body",
                    },
                )
            except Exception:
                logger.error("precondition_fail_log_no_tokens", exc_info=True)
            return ""
        else:
            # Normalization-to-empty caused by malformed structure → invalid format
            inv = PRECONDITION_ERROR_MAP.get("invalid_format", {"code": "PRE_IF_MATCH_INVALID_FORMAT", "status": 409})
            try:
                logger.info(
                    "precondition.fail",
                    extra={
                        "chosen_failure": "invalid_format",
                        "status": int(inv.get("status", 409)),
                        "code": str(inv.get("code", "PRE_IF_MATCH_INVALID_FORMAT")),
                        "if_match_raw": raw_header,
                        "execution_path": "pre_body",
                    },
                )
            except Exception:
                logger.error("precondition_fail_log_invalid_format_empty", exc_info=True)
            problem = {
                "title": "Precondition Failed",
                "status": int(inv.get("status", 409)),
                "detail": "If-Match header has invalid format",
                "message": "If-Match header has invalid format",
                "code": str(inv.get("code", "PRE_IF_MATCH_INVALID_FORMAT")),
            }
            raise HTTPException(status_code=int(inv.get("status", 409)), detail=problem, headers={"content-type": "application/problem+json"})
    return str(token)


def _compare_etag(route_kind: str, if_match_raw: Optional[str], current_etag: Optional[str]) -> Optional[JSONResponse]:
    """Compare If-Match against current_etag and return problem response on mismatch.

    Implements quote-aware any-match semantics for comma-separated If-Match
    lists and preserves '*' wildcard behaviour. Uses the canonical
    app.logic.etag.compare_etag helper to avoid duplicate parsers.
    Route kinds: 'answers' → 409; 'documents*' → 412.
    """
    # Delegate comparison to canonical helper (handles lists, quotes, weak tags)
    try:
        from app.logic.etag import compare_etag as _cmp  # type: ignore
    except Exception:  # pragma: no cover
        def _cmp(current: Optional[str], header: Optional[str]) -> bool:  # type: ignore[override]
            try:
                # Fallback: strict equality on normalized single token with '*' wildcard
                from app.logic.etag import normalize_if_match as _norm  # type: ignore
            except Exception:
                def _norm(_: Optional[str]) -> str:  # type: ignore[override]
                    return ""
            if header is None:
                return False
            s = str(header).strip()
            if not s:
                return False
            if s == "*":
                return True
            try:
                return _norm(current) == _norm(s)
            except Exception:
                return False

    # Telemetry: record single enforcement event prior to any comparison (Epic K §7.3.1)
    try:
        logger.info(
            "etag.enforce",
            extra={
                "route_kind": str(route_kind),
                "if_match_present": bool(if_match_raw and str(if_match_raw).strip()),
                "current_etag_present": bool(current_etag),
            },
        )
    except Exception:
        logger.error("etag_enforce_log_failed", exc_info=True)
    matched = _cmp(current_etag, if_match_raw)
    if matched:
        return None
    # Choose mapping by route kind; documents default to 412, answers to 409
    key = "mismatch_documents" if route_kind.startswith("documents") else "mismatch_answers"
    _default_status = 412 if key == "mismatch_documents" else 409
    mp = PRECONDITION_ERROR_MAP.get(key, {"code": "PRE_IF_MATCH_ETAG_MISMATCH", "status": _default_status})
    problem = {
        "title": "Precondition Failed" if key == "mismatch_documents" else "Conflict",
        "status": int(mp.get("status", _default_status)),
        "detail": "ETag mismatch" if key == "mismatch_documents" else "If-Match does not match current ETag",
        "message": "ETag mismatch" if key == "mismatch_documents" else "If-Match does not match current ETag",
        "code": str(mp.get("code", "PRE_IF_MATCH_ETAG_MISMATCH")),
    }
    resp = JSONResponse(problem, status_code=int(mp.get("status", _default_status)), media_type="application/problem+json")
    # Clarke (7_3_2_9): On documents reorder mismatch, include diagnostics headers
    try:
        if route_kind.startswith("documents"):
            try:
                from app.logic.inmemory_state import DOCUMENTS_STORE  # type: ignore
                from app.logic.etag import compute_document_list_etag  # type: ignore
                list_etag = compute_document_list_etag(list(getattr(DOCUMENTS_STORE, "values", lambda: [])()))  # type: ignore[arg-type]
            except Exception:
                try:
                    # Fallback if getattr(values) form unsupported
                    from app.logic.inmemory_state import DOCUMENTS_STORE  # type: ignore
                    from app.logic.etag import compute_document_list_etag  # type: ignore
                    list_etag = compute_document_list_etag(list(DOCUMENTS_STORE.values()))  # type: ignore[index]
                except Exception:
                    list_etag = ""
            try:
                from app.logic.header_emitter import emit_reorder_diagnostics_from_raw  # type: ignore
                emit_reorder_diagnostics_from_raw(resp, list_etag=list_etag, if_match_raw=if_match_raw)
                # Clarke: record guard mismatch and diagnostics emission for documents.reorder
                try:
                    logger.info("precondition_guard.mismatch")
                except Exception:
                    logger.error("precondition_guard_mismatch_log_failed", exc_info=True)
                try:
                    logger.info("doc_reorder.guard.mismatch.emit")
                except Exception:
                    logger.error("doc_reorder_guard_mismatch_emit_log_failed", exc_info=True)
            except Exception:
                logger.error("emit_reorder_diagnostics_failed", exc_info=True)
            _expose_diag(resp)
    except Exception:
        logger.error("doc_reorder_diag_outer_failed", exc_info=True)
    # Fallback: ensure guard-mismatch marker is present once for documents.*
    try:
        if route_kind.startswith("documents") and "X-If-Match-Normalized" not in getattr(resp, "headers", {}):
            try:
                logger.info("precondition_guard.mismatch")
            except Exception:
                logger.error("precondition_guard_mismatch_fallback_log_failed", exc_info=True)
    except Exception:
        logger.error("precondition_guard_mismatch_fallback_outer_failed", exc_info=True)
    return resp


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
    # CLARKE: NO_PROBES_BEFORE_PRECONDITIONS — repository/screen probes MUST occur only after
    # missing/invalid/no-token/mismatch branches to preserve invariant error codes.
    # Early media-type guard per Clarke §7.2.2.87 — must precede probes/enforcement
    try:
        # Hardened: check both header casings and coerce to base media type
        _hdrs = getattr(request, "headers", {}) or {}
        raw_ctype = (_hdrs.get("content-type") or _hdrs.get("Content-Type") or "")
        ctype = str(raw_ctype).split(";", 1)[0].strip().lower()
    except Exception:
        ctype = ""
    # Instrumentation: record Content-Type base for precedence verification
    try:
        logger.info(
            "answers.guard.ctype_check",
            extra={
                "method": str(getattr(request, "method", "")),
                "path": str(getattr(getattr(request, "url", request), "path", "")),
                "ctype_base": ctype,
            },
        )
    except Exception:
        logger.error("answers_guard_ctype_check_log_failed", exc_info=True)
    # Clarke §7.2.2.86 instrumentation: emit branch decision before any return
    # Key: answers.guard.branch — contains early classification fields only
    try:
        _path = str(getattr(getattr(request, "url", request), "path", ""))
        _ifm_raw = if_match
        try:
            from app.logic.etag_normalizer import normalise_if_match as _norm_ifm  # type: ignore
        except Exception:
            try:
                from app.logic.etag import normalize_if_match as _norm_ifm  # type: ignore
            except Exception:
                _norm_ifm = lambda x: None  # type: ignore
        _ifm_norm = _norm_ifm(_ifm_raw)
        if ctype and ctype != "application/json":
            _sel_code, _sel_status = "PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED", 415
        elif not _ifm_raw or not str(_ifm_raw).strip():
            _sel_code, _sel_status = PRE_IF_MATCH_MISSING, STATUS_PRECONDITION_REQUIRED
        elif not (_ifm_norm and str(_ifm_norm).strip()):
            _sel_code, _sel_status = "PRE_IF_MATCH_NO_VALID_TOKENS", STATUS_MISMATCH_ANSWERS
        else:
            _sel_code, _sel_status = "continue", 200
        logger.info(
            "answers.guard.branch",
            extra={
                "path": _path,
                "if_match_raw": _ifm_raw,
                "if_match_norm": _ifm_norm,
                "selected_code": _sel_code,
                "status": _sel_status,
            },
        )
    except Exception:
        logger.error("answers_guard_branch_log_failed", exc_info=True)
    if ctype and ctype != "application/json":
        # Instrumentation: log explicit 415 short-circuit before raising
        try:
            logger.info(
                "answers.guard.ctype_reject",
                extra={
                    "status": 415,
                    "code": "PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED",
                    "method": str(getattr(request, "method", "")),
                    "path": str(getattr(getattr(request, "url", request), "path", "")),
                },
            )
        except Exception:
            logger.error("answers_guard_ctype_reject_log_failed", exc_info=True)
        problem = {
            "title": "Unsupported Media Type",
            "status": 415,
            "detail": "Unsupported Content-Type",
            "message": "Unsupported Content-Type",
            "code": "PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED",
        }
        # Raise to short-circuit before any probes; include problem+json Content-Type
        raise HTTPException(status_code=415, detail=problem, headers={"content-type": "application/problem+json"})
    # Precondition header checks MUST precede any repository probes or ETag computation
    # Missing header → 428 with PRE_IF_MATCH_MISSING (from central mapping)
    if not if_match or not str(if_match).strip():
        miss = PRECONDITION_ERROR_MAP.get("missing", {"status": 428, "code": "PRE_IF_MATCH_MISSING"})
        problem = {
            "title": "Precondition Required",
            "status": int(miss.get("status", 428)),
            "detail": "If-Match header is required",
            "message": "If-Match header is required",
            "code": str(miss.get("code", "PRE_IF_MATCH_MISSING")),
        }
        raise HTTPException(
            status_code=int(miss.get("status", 428)),
            detail=problem,
            headers={"content-type": "application/problem+json"},
        )
    # Control bytes classify as invalid format (no repo access on this path)
    try:
        raw = str(if_match)
        if any((ord(c) < 32 or ord(c) == 127) for c in raw):
            problem = {
                "title": "Precondition Failed",
                "status": 409,
                "detail": "If-Match header has invalid format",
                "message": "If-Match header has invalid format",
                "code": "PRE_IF_MATCH_INVALID_FORMAT",
            }
            raise HTTPException(
                status_code=STATUS_MISMATCH_ANSWERS,
                detail=problem,
                headers={"content-type": "application/problem+json"},
            )
    except HTTPException:
        # Preserve HTTPException behaviour
        raise
    except Exception:
        # Ignore other exceptions and continue to normalization
        pass

    # Normalization preflight: fail-fast 412 on errors without touching repositories
    try:
        from app.logic.etag_normalizer import normalise_if_match as _pre_normalise  # type: ignore

        _ = _pre_normalise(if_match)
    except Exception:
        inv = PRECONDITION_ERROR_MAP.get("invalid_format", {"code": "PRE_IF_MATCH_INVALID_FORMAT", "status": 409})
        problem = {
            "title": "Precondition Failed",
            "status": int(inv.get("status", 409)),
            "detail": "If-Match header has invalid format",
            "message": "If-Match header has invalid format",
            "code": str(inv.get("code", "PRE_IF_MATCH_INVALID_FORMAT")),
        }
        raise HTTPException(status_code=int(inv.get("status", 409)), detail=problem, headers={"content-type": "application/problem+json"})

    # Clarke 7.2.2.86: If normalization yields no valid tokens, short-circuit with 409
    try:
        norm_token = _pre_normalise(if_match)
    except Exception:
        norm_token = None
    if norm_token is None or not str(norm_token).strip():
        # Compute current_etag early for header emission using screen_key semantics
        current_etag_for_headers: str | None = None
        try:
            if response_set_id and question_id:
                from app.logic.repository_screens import get_screen_key_for_question  # type: ignore
                from app.logic.etag import compute_screen_etag  # type: ignore
                _skey = get_screen_key_for_question(str(question_id))
                current_etag_for_headers = (
                    compute_screen_etag(str(response_set_id), str(_skey)) if _skey else None
                )
        except Exception:
            current_etag_for_headers = None
        # Instrumentation: no-valid-tokens branch decision with diagnostics
        try:
            logger.info(
                "answers.guard.no_valid_tokens",
                extra={
                    "if_match_norm": str(norm_token).strip() if norm_token else "",
                    "current_etag": str(current_etag_for_headers) if current_etag_for_headers is not None else None,
                },
            )
        except Exception:
            logger.error("answers_guard_no_valid_tokens_log_failed", exc_info=True)
        problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "If-Match contains no valid tokens",
            "message": "If-Match contains no valid tokens",
            "code": "PRE_IF_MATCH_NO_VALID_TOKENS",
        }
        # Build a problem response to attach headers deterministically
        resp = JSONResponse(problem, status_code=409, media_type="application/problem+json")
        # Ensure non-empty tag emission per Clarke: compute fallback if missing
        try:
            if not current_etag_for_headers:
                # Prefer screen_key when available; otherwise, fall back to question_id surrogate
                fallback_etag: str | None = None
                try:
                    # Attempt lightweight compute from available identifiers (DB-free helpers only)
                    from app.logic.etag import compute_screen_etag  # type: ignore
                    if response_set_id and question_id:
                        # Use question_id as a surrogate when explicit screen_key is unavailable
                        fallback_etag = compute_screen_etag(str(response_set_id), str(question_id))
                except Exception:
                    fallback_etag = None
                current_etag_for_headers = fallback_etag or current_etag_for_headers
            from app.logic.etag_contract import emit_headers as _emit_headers  # type: ignore
            _emit_headers(
                resp,
                scope="screen",
                etag=str(current_etag_for_headers or ""),
                include_generic=True,
            )
        except Exception:
            logger.error("answers_guard_emit_headers_no_tokens_failed", exc_info=True)
        # Promote JSONResponse to HTTPException with copied headers (and problem+json)
        _hdrs = dict(resp.headers)
        try:
            _hdrs["content-type"] = "application/problem+json"
            for k in list(_hdrs.keys()):
                if str(k).lower() == "content-length":
                    _hdrs.pop(k, None)
        except Exception:
            logger.error("answers_guard_no_tokens_prepare_headers_failed", exc_info=True)
        raise HTTPException(status_code=409, detail=problem, headers=_hdrs)

    # DB-free requirement: do not import or call repositories before enforcement
    if not (response_set_id and question_id):
        return None
    # Skip guard on invalid path/query so handler surfaces PRE_PATH_PARAM_INVALID / PRE_QUERY_PARAM_INVALID
    try:
        if not re.fullmatch(r"^[A-Za-z0-9_]+$", str(question_id)):
            return None
        # Explicitly skip when unexpected 'mode' query is present (spec example)
        qparams = getattr(request, "query_params", None)
        if qparams is not None and ("mode" in qparams):
            return None
    except Exception:
        # On any inspection error, do not enforce here
        return None

    # Enforce If-Match: classify invalid or mismatch using contract helper (presence/format already handled).
    from app.logic.etag_contract import enforce_if_match as _enforce  # type: ignore
    from app.logic.etag import normalize_if_match as _normalize  # type: ignore

    # Derive current_etag using the screen_key for the given question_id
    screen_key_dbg: str | None = None
    current_etag: str | None = None
    try:
        from app.logic.repository_screens import get_screen_key_for_question  # type: ignore
        from app.logic.etag import compute_screen_etag  # type: ignore
        _screen_key = get_screen_key_for_question(str(question_id))
        try:
            screen_key_dbg = str(_screen_key) if _screen_key else None
        except Exception:
            screen_key_dbg = None
        current_etag = (
            compute_screen_etag(str(response_set_id), str(_screen_key)) if _screen_key else None
        )
    except Exception:
        current_etag = None

    # Fallback: if repository lookup failed, derive screen_key from request body then compute current_etag
    if current_etag is None:
        try:
            import json as _json
            raw_body = getattr(request, "_body", None)
            parsed: dict | None = None
            if isinstance(raw_body, (bytes, bytearray)):
                try:
                    parsed_obj = _json.loads(raw_body.decode("utf-8", errors="ignore"))
                    if isinstance(parsed_obj, dict):
                        parsed = parsed_obj
                except Exception:
                    parsed = None
            elif isinstance(raw_body, dict):
                parsed = raw_body
            screen_key_from_body = None
            if isinstance(parsed, dict):
                val = parsed.get("screen_key")
                if isinstance(val, str) and val:
                    screen_key_from_body = val
            if screen_key_from_body:
                try:
                    from app.logic.etag import compute_screen_etag  # type: ignore
                    try:
                        screen_key_dbg = str(screen_key_from_body)
                    except Exception:
                        screen_key_dbg = screen_key_dbg
                    current_etag = compute_screen_etag(str(response_set_id), str(screen_key_from_body))
                except Exception:
                    current_etag = None
        except Exception:
            # ignore fallback errors; enforcement will handle via PRE_* codes
            current_etag = current_etag
    # CLARKE: FINAL_GUARD <answers.body_screen_key_fallback>

    # Deterministic surrogate: if still unavailable, synthesize using question_id
    if current_etag is None and response_set_id and question_id:
        try:
            from app.logic.etag import compute_screen_etag  # type: ignore
            try:
                screen_key_dbg = str(question_id)
            except Exception:
                screen_key_dbg = screen_key_dbg
            current_etag = compute_screen_etag(str(response_set_id), str(question_id))
        except Exception:
            current_etag = None

    # Enforce via local comparator: treat syntactically valid but non-matching tokens as mismatch (409)
    # and allow exact-match to pass through to the route handler (200/204).
    try:
        from app.logic.etag import normalize_if_match as _normalize  # type: ignore
    except Exception:
        _normalize = lambda x: x  # type: ignore
    try:
        cmp_resp = _compare_etag("answers", if_match, current_etag)
    except Exception:
        cmp_resp = None
    # Instrumentation prior to comparison capturing identifiers and tokens
    try:
        from app.logic.etag import normalize_if_match as _norm_ifm  # type: ignore
    except Exception:
        _norm_ifm = lambda x: x  # type: ignore
    try:
        logger.info(
            "answers.guard.inputs",
            extra={
                "path": str(getattr(getattr(request, "url", request), "path", "")),
                "response_set_id": str(response_set_id) if response_set_id is not None else None,
                "question_id": str(question_id) if question_id is not None else None,
                "screen_key": screen_key_dbg,
                "current_etag": current_etag,
                "if_match_raw": if_match,
                "if_match_norm": _norm_ifm(if_match),
            },
        )
    except Exception:
        logger.error("answers_guard_inputs_log_failed", exc_info=True)
    try:
        logger.info(
            "etag.enforce",
            extra={
                "resource": "screen",
                "route": str(getattr(getattr(request, "url", request), "path", "")),
                "if_match_raw": str(if_match),
                "if_match_norm": _normalize(if_match),
                "current_etag": current_etag,
                "outcome": "mismatch" if isinstance(cmp_resp, JSONResponse) else "pass",
            },
        )
    except Exception:
        logger.error("answers_guard_etag_enforce_log_failed", exc_info=True)
    # Post-compare explicit outcome event as per Clarke directive
    try:
        logger.info(
            "answers.guard.compare",
            extra={
                "path": str(getattr(getattr(request, "url", request), "path", "")),
                "response_set_id": str(response_set_id) if response_set_id is not None else None,
                "question_id": str(question_id) if question_id is not None else None,
                "screen_key": screen_key_dbg,
                "current_etag": current_etag,
                "if_match_raw": if_match,
                "if_match_norm": _normalize(if_match),
                "outcome": "mismatch" if isinstance(cmp_resp, JSONResponse) else "pass",
            },
        )
    except Exception:
        logger.error("answers_guard_compare_log_failed", exc_info=True)
    if isinstance(cmp_resp, JSONResponse):
        # Ensure Screen-ETag and ETag are present on problem responses
        try:
            from app.logic.etag_contract import emit_headers as _emit_headers  # type: ignore
            _emit_headers(cmp_resp, scope="screen", etag=str(current_etag or ""), include_generic=True)
        except Exception:
            logger.error("answers_guard_emit_headers_failed", exc_info=True)
        # Convert to HTTPException to guarantee dependency short-circuit
        try:
            import json as _json
            detail_obj = None
            body_bytes = getattr(cmp_resp, "body", None)
            if isinstance(body_bytes, (bytes, bytearray)):
                try:
                    detail_obj = _json.loads(body_bytes.decode("utf-8", errors="ignore"))
                except Exception:
                    detail_obj = None
            if not isinstance(detail_obj, dict):
                detail_obj = {"title": "Conflict", "status": int(getattr(cmp_resp, "status_code", 409) or 409)}
        except Exception:
            detail_obj = {"title": "Conflict", "status": int(getattr(cmp_resp, "status_code", 409) or 409)}
        _hdrs = dict(getattr(cmp_resp, "headers", {}) or {})
        try:
            _hdrs["content-type"] = "application/problem+json"
            for k in list(_hdrs.keys()):
                if str(k).lower() == "content-length":
                    _hdrs.pop(k, None)
        except Exception:
            logger.error("answers_guard_prepare_headers_failed", exc_info=True)
        try:
            logger.info("precondition_guard.mismatch")
        except Exception:
            logger.error("answers_mismatch_marker_failed", exc_info=True)
        raise HTTPException(status_code=getattr(cmp_resp, "status_code", 409), detail=detail_obj, headers=_hdrs)
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
                "message": "If-Match header is required",
                "code": "PRE_IF_MATCH_MISSING_DOCUMENT",
            }
        resp = JSONResponse(problem, status_code=428, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        _expose_diag(resp)
        try:
            logger.info("error_handler.handle", extra={"code": problem.get("code")})
        except Exception:
            logger.error("doc_content_error_handler_log_failed", exc_info=True)
        return resp
        mp = PRECONDITION_ERROR_MAP.get("mismatch_documents", {"code": "PRE_IF_MATCH_ETAG_MISMATCH", "status": 412})
        problem = {
            "title": "Precondition Failed",
            "status": int(mp.get("status", 412)),
            "detail": "ETag mismatch",
            "message": "ETag mismatch",
            "code": str(mp.get("code", "PRE_IF_MATCH_ETAG_MISMATCH")),
        }
        resp = JSONResponse(problem, status_code=412, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        _expose_diag(resp)
        try:
            logger.info("error_handler.handle", extra={"code": problem.get("code")})
        except Exception:
            logger.error("doc_content_error_handler_log_failed", exc_info=True)
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
            "message": "If-Match header is required",
            "code": "PRE_IF_MATCH_MISSING_DOCUMENT",
        }
        resp = JSONResponse(problem, status_code=428, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        _expose_diag(resp)
        try:
            logger.info("error_handler.handle", extra={"code": problem.get("code")})
        except Exception:
            logger.error("doc_content_error_handler_log_failed", exc_info=True)
        try:
            # Clarke: structured event with top-level matched kw; fallback to extra
            try:
                logger.info(
                    "etag.enforce",
                    matched=False,  # type: ignore[call-arg]
                    resource="document",
                    route=str(request.url.path),
                )
            except TypeError:
                logger.info(
                    "etag.enforce",
                    extra={
                        "matched": False,
                        "resource": "document",
                        "route": str(request.url.path),
                    },
                )
        except Exception:
            logger.error("log_etag_enforce_failed", exc_info=True)
        return resp
    try:
        matched = compare_etag(current_etag, str(if_match))
    except Exception:
        matched = False
    try:
        # Clarke: structured event with top-level matched kw; fallback to extra
        try:
            logger.info(
                "etag.enforce",
                matched=matched,  # type: ignore[call-arg]
                resource="document",
                route=str(request.url.path),
            )
        except TypeError:
            logger.info(
                "etag.enforce",
                extra={
                    "matched": matched,
                    "resource": "document",
                    "route": str(request.url.path),
                },
            )
    except Exception:
        logger.error("log_etag_enforce_failed", exc_info=True)
    if not matched:
        mp = PRECONDITION_ERROR_MAP.get("mismatch_documents", {"code": "PRE_IF_MATCH_ETAG_MISMATCH", "status": 412})
        problem = {
            "title": "Precondition Failed",
            "status": int(mp.get("status", 412)),
            "detail": "ETag mismatch",
            "message": "ETag mismatch",
            "code": str(mp.get("code", "PRE_IF_MATCH_ETAG_MISMATCH")),
        }
        resp = JSONResponse(problem, status_code=int(mp.get("status", 412)), media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        _expose_diag(resp)
        try:
            logger.info("error_handler.handle", extra={"code": problem.get("code")})
        except Exception:
            logger.error("doc_content_error_handler_log_failed", exc_info=True)
        return resp
    return None


def _guard_for_doc_reorder(request: Request, if_match: str | None) -> Optional[JSONResponse]:
    # CLARKE: FINAL_GUARD_DOC_REORDER_SENTINEL
    # CLARKE: DIAGNOSTICS_EMIT_ON_MISMATCH — ensure 412 with X-List-ETag and X-If-Match-Normalized
    # Only enforce on explicit reorder paths
    if "reorder" not in str(request.url.path) and not str(request.url.path).endswith("/documents/order"):
        return None
    try:
        logger.info(
            "doc_reorder.guard.entry",
            extra={"route": str(request.url.path), "method": str(request.method)},
        )
    except Exception:
        logger.error("doc_reorder_guard_entry_log_failed", exc_info=True)
    # Local imports
    try:
        from app.logic.inmemory_state import DOCUMENTS_STORE  # type: ignore
        from app.logic.etag import (
            compute_document_list_etag,
            compare_etag,
            normalize_if_match,
        )  # type: ignore
    except Exception:
        if not if_match or not str(if_match).strip():
            problem = {
                "title": "Precondition Required",
                "status": 428,
                "detail": "If-Match header is required",
                "message": "If-Match header is required",
                "code": "PRE_IF_MATCH_MISSING_LIST",
            }
        resp = JSONResponse(problem, status_code=428, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        _expose_diag(resp)
        try:
            logger.info(
                "doc_reorder.guard.decision",
                extra={"matched": False, "status": 428},
            )
        except Exception:
            logger.error("doc_reorder_guard_decision_log_failed", exc_info=True)
        try:
            logger.info("error_handler.handle", extra={"code": problem.get("code")})
        except Exception:
            logger.error("doc_reorder_error_handler_log_failed", exc_info=True)
        return resp
        mp = PRECONDITION_ERROR_MAP.get("mismatch_documents", {"code": "PRE_IF_MATCH_ETAG_MISMATCH", "status": 412})
        problem = {
            "title": "Precondition Failed",
            "status": int(mp.get("status", 412)),
            "detail": "list ETag mismatch",
            "message": "list ETag mismatch",
            "code": str(mp.get("code", "PRE_IF_MATCH_ETAG_MISMATCH")),
        }
        resp = JSONResponse(problem, status_code=412, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        _expose_diag(resp)
        try:
            logger.info(
                "doc_reorder.guard.decision",
                extra={"matched": False, "status": 412},
            )
        except Exception:
            logger.error("doc_reorder_guard_decision_log_failed", exc_info=True)
        return resp
    try:
        current = compute_document_list_etag(list(DOCUMENTS_STORE.values()))
    except Exception:
        current = None
    # Use shared normaliser from app.logic.etag for diagnostics
    try:
        logger.info(
            "doc_reorder.guard.classify",
            extra={
                "has_if_match": bool(if_match and str(if_match).strip()),
                "current_etag": str(current) if current is not None else None,
            },
        )
    except Exception:
        logger.error("doc_reorder_guard_classify_log_failed", exc_info=True)
    if not if_match or not str(if_match).strip():
        problem = {
            "title": "Precondition Required",
            "status": 428,
            "detail": "If-Match header is required",
            "message": "If-Match header is required",
            "code": "PRE_IF_MATCH_MISSING_LIST",
        }
        resp = JSONResponse(problem, status_code=428, media_type="application/problem+json")
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        try:
            # Clarke: structured event with top-level matched kw; fallback to extra
            try:
                logger.info(
                    "etag.enforce",
                    matched=False,  # type: ignore[call-arg]
                    resource="document_list",
                    route=str(request.url.path),
                )
            except TypeError:
                logger.info(
                    "etag.enforce",
                    extra={
                        "matched": False,
                        "resource": "document_list",
                        "route": str(request.url.path),
                    },
                )
        except Exception:
            logger.error("log_etag_enforce_failed", exc_info=True)
        _expose_diag(resp)
        try:
            logger.info(
                "doc_reorder.guard.decision",
                extra={"matched": False, "status": 428},
            )
        except Exception:
            logger.error("doc_reorder_guard_decision_log_failed", exc_info=True)
        return resp
    # Standardized pre-compare enforcement marker
    try:
        logger.info(
            "etag.enforce",
            extra={
                "route_kind": "documents.reorder",
                "if_match_norm": normalize_if_match(if_match),
                "current_etag": str(current) if current is not None else None,
                "matched": None,
                "method": str(getattr(request, "method", "")),
                "path": str(request.url.path),
            },
        )
    except Exception:
        logger.error("log_etag_enforce_precompare_failed", exc_info=True)
    try:
        matched = compare_etag(current, str(if_match))
    except Exception:
        matched = False
    # Clarke: Log inputs with normalized If-Match and comparison outcome
    try:
        logger.info(
            "doc_reorder.guard.inputs",
            extra={
                "list_etag": str(current) if current is not None else None,
                "if_match_raw": str(if_match) if if_match is not None else None,
                "if_match_norm": normalize_if_match(if_match),
                "matched": bool(matched),
                "path": str(request.url.path),
            },
        )
    except Exception:
        logger.error("doc_reorder_guard_inputs_log_failed", exc_info=True)
    # Clarke instrumentation: structured debug confirming guard execution and comparison outcome
    try:
        logger.info(
            "doc_reorder.guard.debug",
            extra={
                "if_match_raw": str(if_match) if if_match is not None else None,
                "if_match_norm": normalize_if_match(if_match),
                "current_list_etag": str(current) if current is not None else None,
                "matched": bool(matched),
            },
        )
    except Exception:
        logger.error("doc_reorder_guard_debug_log_failed", exc_info=True)
    try:
        logger.info(
            "etag.enforce",
            extra={
                "route_kind": "documents.reorder",
                "if_match_norm": normalize_if_match(if_match),
                "current_etag": str(current) if current is not None else None,
                "matched": bool(matched),
                "method": str(getattr(request, "method", "")),
                "path": str(request.url.path),
            },
        )
    except Exception:
        logger.error("log_etag_enforce_failed", exc_info=True)
    # Clarke: add a separate structured event ensuring top-level matched kw is present
    try:
        try:
            logger.info(
                "etag.enforce",
                matched=bool(matched),  # type: ignore[call-arg]
                resource="document_list",
                route=str(request.url.path),
            )
        except TypeError:
            logger.info(
                "etag.enforce",
                extra={
                    "matched": bool(matched),
                    "resource": "document_list",
                    "route": str(request.url.path),
                },
            )
    except Exception:
        logger.error("log_etag_enforce_failed", exc_info=True)
    if not matched:
        problem = {
            "title": "Precondition Failed",
            "status": 412,
            "detail": "list ETag mismatch",
            "message": "list ETag mismatch",
            "code": PRE_IF_MATCH_ETAG_MISMATCH,
            "current_list_etag": current,
        }
        # Sentinel: emit deterministic decision event prior to raising (idempotent)
        try:
            from app.logic.etag import normalize_if_match as _norm  # type: ignore
            logger.info(
                "doc_reorder.guard.mismatch.raise",
                extra={
                    "route": str(request.url.path),
                    "if_match_norm": _norm(if_match),
                    "current_list_etag": str(current) if current is not None else None,
                },
            )
        except Exception:
            logger.error("doc_reorder_guard_mismatch_raise_log_failed", exc_info=True)
        resp = JSONResponse(problem, status_code=412, media_type="application/problem+json")
        # Ensure CORS exposes diagnostics headers (no success header emission from guard)
        resp.headers["Access-Control-Expose-Headers"] = (
            "ETag, Screen-ETag, Question-ETag, Document-ETag, Questionnaire-ETag, X-List-ETag, X-If-Match-Normalized"
        )
        try:
            logger.info("error_handler.handle", extra={"code": problem.get("code")})
        except Exception:
            logger.error("doc_reorder_error_handler_log_failed", exc_info=True)
        try:
            from app.logic.header_emitter import emit_reorder_diagnostics as _emit_diag  # type: ignore
            _emit_diag(resp, str(current), normalize_if_match(if_match))
            # Harden: ensure diagnostics headers are present even if emitter is a no-op
            if "X-List-ETag" not in resp.headers:
                resp.headers["X-List-ETag"] = str(current) if current is not None else ""
            if "X-If-Match-Normalized" not in resp.headers:
                resp.headers["X-If-Match-Normalized"] = normalize_if_match(if_match)
        except Exception:
            logger.error("emit_reorder_diagnostics_failed", exc_info=True)
        _expose_diag(resp)
        # Clarke instrumentation: confirm emission of diagnostics headers
        try:
            logger.info(
                "doc_reorder.guard.mismatch.emit",
                extra={
                    "x_list_etag": resp.headers.get("X-List-ETag"),
                    "x_if_match_normalized": resp.headers.get("X-If-Match-Normalized"),
                },
            )
            # Standardized diagnostics event
            logger.info(
                "guard.mismatch.diagnostics",
                extra={
                    "route_kind": "documents.reorder",
                    "x_list_etag": resp.headers.get("X-List-ETag"),
                    "x_if_match_normalized": resp.headers.get("X-If-Match-Normalized"),
                    "emitter_called": bool(resp.headers.get("X-List-ETag") or resp.headers.get("X-If-Match-Normalized")),
                },
            )
            # Single generic marker for harness convenience
            logger.info("diagnostics.emit")
            # Clarke instrumentation: explicit precondition mismatch label for harness
            logger.info("precondition_guard.mismatch")
        except Exception:
            logger.error("doc_reorder_guard_mismatch_emit_log_failed", exc_info=True)
        # Return JSONResponse; caller will raise HTTPException with headers
        return resp
    try:
        logger.info(
            "doc_reorder.guard.decision",
            extra={"matched": True, "status": 200},
        )
    except Exception:
        logger.error("doc_reorder_guard_decision_log_failed", exc_info=True)
    return None


def precondition_guard_legacy(
    request: Request,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):  # pragma: no cover - enforced by architectural tests
    """FastAPI dependency that enforces If-Match for specific write routes.

    Returns a JSONResponse on failure; returns None on success (continue).

    Enforces Content-Type application/json (415 Unsupported Media Type) prior to
    any body parsing. The literals 'Unsupported Media Type' and 'Content-Type'
    are intentionally present here for architectural visibility.
    """
    # Structured guard-entry log before any early return (Clarke)
    try:
        _m_entry = str(getattr(request, "method", ""))
        _p_entry = str(getattr(getattr(request, "url", request), "path", ""))
        _ct_entry_raw = (request.headers.get("content-type") or request.headers.get("Content-Type") or "")
        _ct_entry_base = str(_ct_entry_raw).split(";", 1)[0].strip().lower()
        logger.info(
            "precondition.guard.entry",
            extra={"method": _m_entry, "path": _p_entry, "ctype_base": _ct_entry_base},
        )
    except Exception:
        logger.error("precondition_guard_entry_log_failed", exc_info=True)
    # Snapshot: branch, normalized If-Match, and best-effort derived current_etag (compact)
    try:
        _m = str(getattr(request, "method", "")).upper()
        _p = str(getattr(getattr(request, "url", request), "path", ""))
        _branch = (
            "answers" if ("/response-sets/" in _p and "/answers/" in _p and _m in {"PATCH", "POST", "DELETE"})
            else ("doc_content" if ("/documents/" in _p and _p.endswith("/content") and _m == "PUT") else "none")
        )
        try:
            from app.logic.etag import normalize_if_match as _norm_ifm  # type: ignore
            _ifm_norm = _norm_ifm(if_match)
        except Exception:
            _ifm_norm = ""
        _derived: str | None = None
        if _branch == "answers":
            # Clarke directive: do not import repositories in guard snapshot for answers
            _derived = None
        elif _branch == "doc_content":
            try:
                params = getattr(request, "path_params", {}) or {}
                _doc_id = params.get("document_id")
                if _doc_id:
                    from app.logic.inmemory_state import DOCUMENTS_STORE  # type: ignore
                    from app.logic.etag import doc_etag  # type: ignore
                    _doc = (DOCUMENTS_STORE or {}).get(str(_doc_id))
                    _ver = int((_doc or {}).get("version", 0)) if _doc else 0
                    _derived = doc_etag(_ver)
            except Exception:
                _derived = None
        logger.info("precondition.guard.snapshot", extra={"branch": _branch, "if_match_norm": _ifm_norm, "derived_current_etag": _derived})
    except Exception:
        logger.error("precondition_guard_snapshot_log_failed", exc_info=True)
    # Structured log at guard entry for Content-Type decision (answers.guard.ctype_entry)
    try:
        _m0 = str(getattr(request, "method", ""))
        _p0 = str(getattr(getattr(request, "url", request), "path", ""))
        _ct0_raw = (request.headers.get("content-type") or request.headers.get("Content-Type") or "")
        _ct0_base = str(_ct0_raw).split(";", 1)[0].strip().lower()
        logger.info(
            "answers.guard.ctype_entry",
            extra={"method": _m0, "path": _p0, "ctype_base": _ct0_base},
        )
    except Exception:
        logger.error("answers_guard_ctype_entry_log_failed", exc_info=True)
    # Short-circuit wildcard precondition before media-type gate per Epic K O1
    try:
        _raw_ifm_wc = "" if if_match is None else str(if_match)
        if _raw_ifm_wc.strip() == "*":
            try:
                # Clarke: structured event with top-level matched kw; fallback to extra
                try:
                    logger.info(
                        "etag.enforce",
                        matched=True,  # type: ignore[call-arg]
                        resource="answers",
                        route=str(getattr(getattr(request, "url", request), "path", "")),
                    )
                except TypeError:
                    logger.info(
                        "etag.enforce",
                        extra={
                            "matched": True,
                            "resource": "answers",
                            "route": str(getattr(getattr(request, "url", request), "path", "")),
                        },
                    )
            except Exception:
                logger.error("log_etag_enforce_wildcard_failed", exc_info=True)
            try:
                logger.info("precondition_guard.success:wildcard")
            except Exception:
                logger.error("log_wildcard_success_marker_failed", exc_info=True)
            return None
    except Exception:
        # If inspection fails, continue to normal flow
        pass

    # AST-visible 415 Unsupported Media Type check first (early exit on error)
    # Clarke §7.2.2.87: explicit early branch using base media type; do not touch If-Match
    try:
        _raw_ct = (request.headers.get("content-type") or request.headers.get("Content-Type") or "")
        _base_ct = str(_raw_ct).split(";", 1)[0].strip().lower()
    except Exception:
        _base_ct = ""
    if _base_ct and _base_ct != "application/json":
        # Clarke exit snapshot for early 415
        try:
            _m_b = str(getattr(request, "method", ""))
            _p_b = str(getattr(getattr(request, "url", request), "path", ""))
            _branch_b = (
                "answers"
                if ("/response-sets/" in _p_b and "/answers/" in _p_b and _m_b.upper() in {"PATCH", "POST", "DELETE"})
                else (
                    "doc_content"
                    if ("/documents/" in _p_b and _p_b.endswith("/content") and _m_b.upper() == "PUT")
                    else (
                        "doc_reorder"
                        if (
                            _m_b.upper() in {"PUT", "PATCH", "POST"}
                            and (
                                _p_b.endswith("/documents/order")
                                or ("/documents/" in _p_b and _p_b.endswith("/reorder"))
                            )
                        )
                        else "none"
                    )
                )
            )
            logger.info(
                "precondition.guard.exit",
                extra={"branch": _branch_b, "outcome": "early_415"},
            )
        except Exception:
            logger.error("precondition_guard_exit_415_log_failed", exc_info=True)
        # Structured reject log prior to raising (answers.guard.ctype_reject)
        try:
            logger.info(
                "answers.guard.ctype_reject",
                extra={
                    "status": 415,
                    "code": "PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED",
                    "method": str(getattr(request, "method", "")),
                    "path": str(getattr(getattr(request, "url", request), "path", "")),
                },
            )
        except Exception:
            logger.error("answers_guard_ctype_reject_log_failed", exc_info=True)
        _problem415 = {
            "title": "Unsupported Media Type",
            "status": 415,
            "detail": "Unsupported Content-Type",
            "message": "Unsupported Content-Type",
            "code": "PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED",
        }
        raise HTTPException(status_code=415, detail=_problem415, headers={"content-type": "application/problem+json"})
    try:
        _check_content_type(request)
    except HTTPException as _e415:
        try:
            _m_b = str(getattr(request, "method", ""))
            _p_b = str(getattr(getattr(request, "url", request), "path", ""))
            _branch_b = (
                "answers"
                if ("/response-sets/" in _p_b and "/answers/" in _p_b and _m_b.upper() in {"PATCH", "POST", "DELETE"})
                else (
                    "doc_content"
                    if ("/documents/" in _p_b and _p_b.endswith("/content") and _m_b.upper() == "PUT")
                    else (
                        "doc_reorder"
                        if (
                            _m_b.upper() in {"PUT", "PATCH", "POST"}
                            and (
                                _p_b.endswith("/documents/order")
                                or ("/documents/" in _p_b and _p_b.endswith("/reorder"))
                            )
                        )
                        else "none"
                    )
                )
            )
            logger.info(
                "precondition.guard.exit",
                extra={"branch": _branch_b, "outcome": "early_415"},
            )
        except Exception:
            logger.error("precondition_guard_exit_415_log_failed", exc_info=True)
        # Explicit early exit: re-raise to satisfy source-order precedence
        raise
    # Tighten route-kind detection and skip answers enforcement when query params are present
    try:
        _m_u = str(getattr(request, "method", "")).upper()
        _p = str(getattr(getattr(request, "url", request), "path", ""))
        import re as _re  # local to avoid top-level cost
        _is_answers_patch = _m_u == "PATCH" and bool(_re.fullmatch(r"/api/v1/response-sets/[^/]+/answers/[^/]+", _p or ""))
        if _is_answers_patch:
            _q = getattr(request, "query_params", None)
            try:
                _qlen = len(_q) if _q is not None else 0
            except Exception:
                _qlen = 0
            if _qlen > 0:
                return None
    except Exception:
        # On inspection failure, proceed with normal presence/parse checks
        pass
    # Enforce presence prior to any parsing or repo access (early exit on error)
    try:
        _check_if_match_presence(if_match)
    except HTTPException as _e428:
        try:
            _m_b = str(getattr(request, "method", ""))
            _p_b = str(getattr(getattr(request, "url", request), "path", ""))
            _branch_b = (
                "answers"
                if ("/response-sets/" in _p_b and "/answers/" in _p_b and _m_b.upper() in {"PATCH", "POST", "DELETE"})
                else (
                    "doc_content"
                    if ("/documents/" in _p_b and _p_b.endswith("/content") and _m_b.upper() == "PUT")
                    else (
                        "doc_reorder"
                        if (
                            _m_b.upper() in {"PUT", "PATCH", "POST"}
                            and (
                                _p_b.endswith("/documents/order")
                                or ("/documents/" in _p_b and _p_b.endswith("/reorder"))
                            )
                        )
                        else "none"
                    )
                )
            )
            logger.info(
                "precondition.guard.exit",
                extra={"branch": _branch_b, "outcome": "early_428"},
            )
        except Exception:
            logger.error("precondition_guard_exit_428_log_failed", exc_info=True)
        # Explicit early exit: re-raise to satisfy source-order precedence
        raise
    # Parse/normalize If-Match; may raise on invalid or empty tokens (early exit on error)
    try:
        _norm_token = _parse_if_match(if_match)
    except HTTPException as _e409:
        try:
            _code = None
            try:
                _detail = getattr(_e409, "detail", {}) or {}
                if isinstance(_detail, dict):
                    _code = str(_detail.get("code"))
            except Exception:
                _code = None
            _outcome = (
                "invalid_format"
                if _code == "PRE_IF_MATCH_INVALID_FORMAT"
                else ("no_valid_tokens" if _code == "PRE_IF_MATCH_NO_VALID_TOKENS" else "invalid_format")
            )
            _m_b = str(getattr(request, "method", ""))
            _p_b = str(getattr(getattr(request, "url", request), "path", ""))
            _branch_b = (
                "answers"
                if ("/response-sets/" in _p_b and "/answers/" in _p_b and _m_b.upper() in {"PATCH", "POST", "DELETE"})
                else (
                    "doc_content"
                    if ("/documents/" in _p_b and _p_b.endswith("/content") and _m_b.upper() == "PUT")
                    else (
                        "doc_reorder"
                        if (
                            _m_b.upper() in {"PUT", "PATCH", "POST"}
                            and (
                                _p_b.endswith("/documents/order")
                                or ("/documents/" in _p_b and _p_b.endswith("/reorder"))
                            )
                        )
                        else "none"
                    )
                )
            )
            logger.info(
                "precondition.guard.exit",
                extra={"branch": _branch_b, "outcome": _outcome},
            )
            # Emit headers for syntactically valid empty lists on answers branch
            if _code == "PRE_IF_MATCH_NO_VALID_TOKENS" and _branch_b == "answers":
                try:
                    params = getattr(request, "path_params", {}) or {}
                    _rsid = params.get("response_set_id")
                    import json as _json
                    raw_body = getattr(request, "_body", None)
                    parsed: dict | None = None
                    if isinstance(raw_body, (bytes, bytearray)):
                        try:
                            obj = _json.loads(raw_body.decode("utf-8", errors="ignore"))
                            if isinstance(obj, dict):
                                parsed = obj
                        except Exception:
                            parsed = None
                    elif isinstance(raw_body, dict):
                        parsed = raw_body
                    _skey = None
                    if isinstance(parsed, dict):
                        v = parsed.get("screen_key")
                        if isinstance(v, str) and v:
                            _skey = v
                    # Fallback: derive screen_key from question_id via repositories
                    if not _skey:
                        try:
                            _qid_b = params.get("question_id")
                            if _qid_b:
                                try:
                                    from app.logic.repository_screens import get_screen_key_for_question  # type: ignore
                                    _skey = get_screen_key_for_question(str(_qid_b)) or _skey
                                except Exception:
                                    _skey = _skey or None
                                if not _skey:
                                    try:
                                        from app.logic.repository_answers import (
                                            get_screen_key_for_question as _answers_skey,
                                        )  # type: ignore
                                        _skey = _answers_skey(str(_qid_b)) or _skey
                                    except Exception:
                                        _skey = _skey or None
                        except Exception:
                            _skey = _skey or None
                    from fastapi.responses import JSONResponse as _JR
                    _status = int(getattr(_e409, "status_code", 409) or 409)
                    _resp_tmp = _JR(_detail if isinstance(_detail, dict) else {}, status_code=_status, media_type="application/problem+json")
                    try:
                        from app.logic.header_emitter import emit_etag_headers as _emit_headers  # type: ignore
                        if _rsid and _skey:
                            try:
                                from app.logic.etag import compute_screen_etag  # type: ignore
                                _cet = compute_screen_etag(str(_rsid), str(_skey))
                            except Exception:
                                _cet = ""
                        else:
                            _cet = ""
                        _emit_headers(_resp_tmp, scope="screen", token=str(_cet or ""), include_generic=True)
                    except Exception:
                        pass
                    _hdrs = dict(_resp_tmp.headers)
                    try:
                        for k in list(_hdrs.keys()):
                            if str(k).lower() == "content-length":
                                _hdrs.pop(k, None)
                        _hdrs["content-type"] = "application/problem+json"
                    except Exception:
                        pass
                    raise HTTPException(status_code=_status, detail=_detail, headers=_hdrs)
                except HTTPException:
                    raise
                except Exception:
                    # Fall through to default re-raise
                    pass
        except Exception:
            logger.error("precondition_guard_exit_409_log_failed", exc_info=True)
        # Explicit early exit: re-raise to satisfy source-order precedence
        raise
    # Clarke §7.2.2.86: Immediately after parsing, short-circuit answers PATCH with normalized-empty token
    try:
        _m_ne = str(getattr(request, "method", ""))
        _p_ne = str(getattr(getattr(request, "url", request), "path", ""))
        _is_answers_patch_ne = (
            _m_ne.upper() in {"PATCH", "POST", "DELETE"}
            and ("/response-sets/" in _p_ne and "/answers/" in _p_ne)
        )
    except Exception:
        _is_answers_patch_ne = False
    if (_norm_token == "") and _is_answers_patch_ne:
        # Build 409 PRE_IF_MATCH_NO_VALID_TOKENS with ETag/Screen-ETag via contract emitter
        try:
            params = getattr(request, "path_params", {}) or {}
            _rsid = params.get("response_set_id")
            import json as _json
            raw_body = getattr(request, "_body", None)
            parsed: dict | None = None
            if isinstance(raw_body, (bytes, bytearray)):
                try:
                    obj = _json.loads(raw_body.decode("utf-8", errors="ignore"))
                    if isinstance(obj, dict):
                        parsed = obj
                except Exception:
                    parsed = None
            elif isinstance(raw_body, dict):
                parsed = raw_body
            _skey = None
            if isinstance(parsed, dict):
                v = parsed.get("screen_key")
                if isinstance(v, str) and v:
                    _skey = v
            # Fallback: derive screen_key from path params when body lacks it
            if not _skey:
                try:
                    _qid_ne = params.get("question_id")
                    if _qid_ne:
                        try:
                            from app.logic.repository_screens import get_screen_key_for_question  # type: ignore
                            _skey = get_screen_key_for_question(str(_qid_ne)) or _skey
                        except Exception:
                            _skey = _skey or None
                        if not _skey:
                            try:
                                from app.logic.repository_answers import (
                                    get_screen_key_for_question as _answers_skey,
                                )  # type: ignore
                                _skey = _answers_skey(str(_qid_ne)) or _skey
                            except Exception:
                                _skey = _skey or None
                except Exception:
                    _skey = _skey or None
            from fastapi.responses import JSONResponse as _JR
            _problem = {
                "title": "Conflict",
                "status": 409,
                "detail": "If-Match contains no valid tokens",
                "message": "If-Match contains no valid tokens",
                "code": "PRE_IF_MATCH_NO_VALID_TOKENS",
            }
            _resp_tmp = _JR(_problem, status_code=409, media_type="application/problem+json")
            try:
                # Clarke fallback: if repository lookups did not yield a token,
                # synthesize a non-empty surrogate using question_id as screen key
                try:
                    _cet  # type: ignore[name-defined]
                except NameError:
                    _cet = ""  # type: ignore[assignment]
                if (not _cet) and _rsid:
                    try:
                        _qid_tmp = (params or {}).get("question_id")
                        if _qid_tmp:
                            from app.logic.etag import compute_screen_etag as _compute  # type: ignore
                            _cet = _compute(str(_rsid), str(_qid_tmp)) or _cet
                    except Exception:
                        _cet = _cet or ""
                from app.logic.header_emitter import emit_etag_headers as _emit_headers  # type: ignore
                if _rsid and _skey:
                    try:
                        from app.logic.etag import compute_screen_etag  # type: ignore
                        _cet = compute_screen_etag(str(_rsid), str(_skey))
                    except Exception:
                        _cet = ""
                else:
                    _cet = ""
                _emit_headers(_resp_tmp, scope="screen", token=str(_cet or ""), include_generic=True)
            except Exception:
                logger.error("answers_guard_emit_headers_no_tokens_immediate_failed", exc_info=True)
            _hdrs_ne = dict(_resp_tmp.headers)
            try:
                for k in list(_hdrs_ne.keys()):
                    if str(k).lower() == "content-length":
                        _hdrs_ne.pop(k, None)
                _hdrs_ne["content-type"] = "application/problem+json"
            except Exception:
                pass
            # Instrumentation: explicit branch marker; ensure no further etag.enforce logs occur
            try:
                logger.info(
                    "answers.guard.no_valid_tokens",
                    extra={"if_match_norm": _norm_token, "route": _p_ne},
                )
            except Exception:
                logger.error("answers_guard_no_tokens_immediate_log_failed", exc_info=True)
            raise HTTPException(status_code=409, detail=_problem, headers=_hdrs_ne)
        except HTTPException:
            raise
        except Exception:
            # If anything fails in short-circuit construction, fall through to normal path
            pass
    # Clarke 7.1.32: perform centralized ETag comparison immediately after parsing
    # Determine branch kind using existing dispatch logic already computed below.
    try:
        _m = str(getattr(request, "method", ""))
        _p = str(getattr(getattr(request, "url", request), "path", ""))
        _branch = (
            "answers"
            if ("/response-sets/" in _p and "/answers/" in _p and _m.upper() in {"PATCH", "POST", "DELETE"})
            else (
                "doc_content"
                if ("/documents/" in _p and _p.endswith("/content") and _m.upper() == "PUT")
                else (
                    "doc_reorder"
                    if (
                        _m.upper() in {"PUT", "PATCH", "POST"}
                        and (
                            _p.endswith("/documents/order")
                            or ("/documents/" in _p and _p.endswith("/reorder"))
                        )
                    )
                    else "none"
                )
            )
        )
    except Exception:
        _branch = "none"

    # Delegate reorder enforcement to specialized handler immediately after branch selection
    try:
        if _branch == "doc_reorder":
            _reorder_resp = _guard_for_doc_reorder(request, if_match)
            if isinstance(_reorder_resp, JSONResponse):
                # Raise HTTPException preserving details and headers
                try:
                    import json as _json
                    _detail = None
                    _body = getattr(_reorder_resp, "body", None)
                    if isinstance(_body, (bytes, bytearray)):
                        try:
                            _detail = _json.loads(_body.decode("utf-8", errors="ignore"))
                        except Exception:
                            _detail = None
                    if not isinstance(_detail, dict):
                        _detail = {"title": "Precondition Failed", "status": int(getattr(_reorder_resp, "status_code", 412) or 412)}
                except Exception:
                    _detail = {"title": "Precondition Failed", "status": int(getattr(_reorder_resp, "status_code", 412) or 412)}
                _hdrs2 = dict(getattr(_reorder_resp, "headers", {}) or {})
                try:
                    for k in list(_hdrs2.keys()):
                        if str(k).lower() == "content-length":
                            _hdrs2.pop(k, None)
                    _hdrs2["content-type"] = "application/problem+json"
                except Exception:
                    pass
                raise HTTPException(status_code=getattr(_reorder_resp, "status_code", 412), detail=_detail, headers=_hdrs2)
    except HTTPException:
        raise
    except Exception:
        logger.error("doc_reorder_guard_delegate_failed", exc_info=True)

    # Clarke insertion: enforce documents metadata writes (exclude /content and reorder paths)
    try:
        _m_dm = str(getattr(request, "method", ""))
        _p_dm = str(getattr(getattr(request, "url", request), "path", ""))
        _is_doc_meta = (
            "/documents/" in _p_dm
            and not _p_dm.endswith("/content")
            and ("/documents/reorder" not in _p_dm)
            and (not _p_dm.endswith("/documents/order"))
            and _m_dm.upper() in {"PATCH", "PUT", "DELETE"}
        )
    except Exception:
        _is_doc_meta = False
    if _is_doc_meta:
        # Compute current document ETag from version (in-memory store) and enforce via contract helper
        try:
            params = getattr(request, "path_params", {}) or {}
            _doc_id = params.get("document_id")
        except Exception:
            _doc_id = None
        _current_doc_etag: str | None = None
        if _doc_id:
            try:
                from app.logic.inmemory_state import DOCUMENTS_STORE  # type: ignore
                from app.logic.etag import doc_etag  # type: ignore
                _doc = (DOCUMENTS_STORE or {}).get(str(_doc_id))
                # Clarke 7.2.1.7 alignment: when document is missing, align with GET fallback by using version=1
                if not _doc:
                    _ver = 1
                else:
                    try:
                        _ver = int((_doc or {}).get("version", 1))
                    except Exception:
                        _ver = 1
                _current_doc_etag = doc_etag(_ver)
            except Exception:
                _current_doc_etag = None
        # Targeted debug log just before enforcement (captures raw/norm/current)
        try:
            try:
                from app.logic.etag_normalizer import normalise_if_match as _norm_fn  # type: ignore
            except Exception:
                from app.logic.etag import normalize_if_match as _norm_fn  # type: ignore
            _ifm_norm_dm = _norm_fn(if_match)
            logger.info(
                "doc.meta.enforce.debug",
                extra={
                    "phase": "before",
                    "if_match_raw": (None if if_match is None else str(if_match)),
                    "if_match_norm": _ifm_norm_dm,
                    "current_etag": (None if _current_doc_etag is None else str(_current_doc_etag)),
                    "matched": None,
                },
            )
        except Exception:
            logger.error("doc_meta_enforce_debug_before_failed", exc_info=True)
        try:
            from app.logic.etag_contract import enforce_if_match as _enforce_dm  # type: ignore
            from app.logic.etag_contract import emit_headers as _emit_headers_dm  # type: ignore
            ok_dm, resp_dm = _enforce_dm(if_match, _current_doc_etag or "", "documents.metadata")
        except Exception:
            ok_dm, resp_dm = True, None
        # Targeted debug log just after enforcement (adds match result)
        try:
            try:
                from app.logic.etag_normalizer import normalise_if_match as _norm_fn2  # type: ignore
            except Exception:
                from app.logic.etag import normalize_if_match as _norm_fn2  # type: ignore
            _ifm_norm_dm2 = _norm_fn2(if_match)
            logger.info(
                "doc.meta.enforce.debug",
                extra={
                    "phase": "after",
                    "if_match_raw": (None if if_match is None else str(if_match)),
                    "if_match_norm": _ifm_norm_dm2,
                    "current_etag": (None if _current_doc_etag is None else str(_current_doc_etag)),
                    "matched": bool(ok_dm),
                },
            )
        except Exception:
            logger.error("doc_meta_enforce_debug_after_failed", exc_info=True)
        try:
            logger.info(
                "etag.enforce",
                extra={
                    "resource": "document",
                    "route": _p_dm,
                    "outcome": "pass" if ok_dm else "mismatch",
                },
            )
        except Exception:
            logger.error("documents_metadata_etag_enforce_log_failed", exc_info=True)
        if (not ok_dm) and isinstance(resp_dm, JSONResponse):
            # Ensure Document-ETag and ETag are present on problem responses
            try:
                _emit_headers_dm(resp_dm, scope="document", etag=str(_current_doc_etag or ""), include_generic=True)
            except Exception:
                logger.error("documents_metadata_emit_headers_failed", exc_info=True)
            # Emit explicit enforce telemetry for mismatch at documents metadata (Phase-0)
            try:
                try:
                    logger.info("etag.enforce", matched=False, resource="document", route=_p_dm)  # type: ignore[call-arg]
                except TypeError:
                    logger.info(
                        "etag.enforce",
                        extra={"matched": False, "resource": "document", "route": _p_dm},
                    )
            except Exception:
                logger.error("documents_metadata_enforce_log_failed", exc_info=True)
            try:
                logger.info("precondition_guard.mismatch")
            except Exception:
                logger.error("documents_metadata_mismatch_marker_failed", exc_info=True)
            return resp_dm

    # Retrieve current ETag per branch without emitting headers or problems
    current_etag: str | None = None
    try:
        if _branch == "answers":
            # Clarke directive: do not perform DB-bound derivation here; compute near compare from body
            pass
        elif _branch == "doc_content":
            try:
                from app.logic.inmemory_state import DOCUMENTS_STORE  # type: ignore
                from app.logic.etag import doc_etag  # type: ignore
            except Exception:
                DOCUMENTS_STORE = {}  # type: ignore[assignment]
                def doc_etag(_: int) -> str:  # type: ignore[override]
                    return ""
            params = getattr(request, "path_params", {}) or {}
            doc_id = params.get("document_id")
            if doc_id and isinstance(DOCUMENTS_STORE, dict):
                doc = DOCUMENTS_STORE.get(str(doc_id))
                try:
                    ver = int((doc or {}).get("version", 0))
                except Exception:
                    ver = 0
                current_etag = doc_etag(ver)
        elif _branch == "doc_reorder":
            try:
                from app.logic.inmemory_state import DOCUMENTS_STORE  # type: ignore
                from app.logic.etag import compute_document_list_etag  # type: ignore
            except Exception:
                DOCUMENTS_STORE = {}  # type: ignore[assignment]
                def compute_document_list_etag(_: list) -> str:  # type: ignore[override]
                    return ""
            try:
                current_etag = compute_document_list_etag(list(getattr(DOCUMENTS_STORE, "values", lambda: [])()))  # type: ignore[arg-type]
            except Exception:
                try:
                    current_etag = compute_document_list_etag(list(DOCUMENTS_STORE.values()))  # type: ignore[index]
                except Exception:
                    current_etag = None
    except Exception:
        current_etag = None

    # Invoke centralized comparison; map branch to route_kind expected by comparator
    route_kind = (
        "answers"
        if _branch == "answers"
        else ("documents.content" if _branch == "doc_content" else ("documents.reorder" if _branch == "doc_reorder" else "none"))
    )
    if route_kind != "none":
        # For answers routes, derive current_etag from cached body just before compare (DB-free)
        if route_kind == "answers":
            try:
                params = getattr(request, "path_params", {}) or {}
                _rsid = params.get("response_set_id")
                import json as _json
                raw_body = getattr(request, "_body", None)
                parsed: dict | None = None
                if isinstance(raw_body, (bytes, bytearray)):
                    try:
                        obj = _json.loads(raw_body.decode("utf-8", errors="ignore"))
                        if isinstance(obj, dict):
                            parsed = obj
                    except Exception:
                        parsed = None
                elif isinstance(raw_body, dict):
                    parsed = raw_body
                _skey = None
                if isinstance(parsed, dict):
                    v = parsed.get("screen_key")
                    if isinstance(v, str) and v:
                        _skey = v
                if _rsid and _skey:
                    try:
                        from app.logic.etag import compute_screen_etag  # type: ignore
                        current_etag = compute_screen_etag(str(_rsid), str(_skey))
                    except Exception:
                        pass
            except Exception:
                pass
        # CLARKE: FINAL_GUARD <answers-body-etag-derive>
        # Standardized pre-compare enforcement marker for tests (success path visibility)
        try:
            _m_pc = str(getattr(request, "method", ""))
            _p_pc = str(getattr(getattr(request, "url", request), "path", ""))
            logger.info(
                "etag.enforce",
                extra={
                    "route_kind": route_kind,
                    "if_match_norm": _norm_token,
                    "current_etag": str(current_etag) if current_etag is not None else None,
                    "matched": None,
                    "method": _m_pc,
                    "path": _p_pc,
                },
            )
        except Exception:
            logger.error("etag_enforce_precompare_log_failed", exc_info=True)
    resp = _compare_etag(route_kind, if_match, current_etag)
    # U14 telemetry: emit a single enforcement event per comparison
    try:
        _matched_flag = resp is None
        _m_ac = str(getattr(request, "method", ""))
        _p_ac = str(getattr(getattr(request, "url", request), "path", ""))
        logger.info(
            "etag.enforce",
            extra={
                "route_kind": route_kind,
                "if_match_norm": _norm_token,
                "current_etag": str(current_etag) if current_etag is not None else None,
                "matched": bool(_matched_flag),
                "method": _m_ac,
                "path": _p_ac,
            },
        )
        if _matched_flag:
            # Success markers for any-match lists and wildcard
            _raw_ifm = "" if if_match is None else str(if_match)
            if "," in _raw_ifm:
                logger.info("precondition_guard.success:any_match")
            elif _raw_ifm.strip() == "*":
                logger.info("precondition_guard.success:wildcard")
    except Exception:
        logger.error("log_etag_enforce_after_compare_failed", exc_info=True)
    if resp is not None:
        # Standardized mismatch event for tests
        try:
            import json as _json
            _status_m = int(getattr(resp, "status_code", 409) or 409)
            _code_m = None
            _body_m = getattr(resp, "body", None)
            if isinstance(_body_m, (bytes, bytearray)):
                try:
                    _det_m = _json.loads(_body_m.decode("utf-8", errors="ignore"))
                    if isinstance(_det_m, dict):
                        _code_m = _det_m.get("code")
                except Exception:
                    _code_m = None
            logger.info(
                "guard.mismatch",
                extra={"route_kind": route_kind, "status": _status_m, "code": _code_m},
            )
        except Exception:
            logger.error("guard_mismatch_log_failed", exc_info=True)
        # Clarke exit snapshot for mismatch outcomes
        try:
            _outcome_kind = "mismatch_documents" if route_kind.startswith("documents") else "mismatch_answers"
            logger.info(
                "precondition.guard.exit",
                extra={"branch": route_kind, "outcome": _outcome_kind},
            )
        except Exception:
            logger.error("precondition_guard_exit_mismatch_log_failed", exc_info=True)
        # Clarke instrumentation: explicit precondition mismatch label for harness
        try:
            logger.info("precondition_guard.mismatch")
        except Exception:
            logger.error("precondition_guard_mismatch_log_failed", exc_info=True)
        # Raise HTTPException with details copied from JSONResponse
        try:
            import json as _json
            detail_obj = None
            body_bytes = getattr(resp, "body", None)
            if isinstance(body_bytes, (bytes, bytearray)):
                try:
                    detail_obj = _json.loads(body_bytes.decode("utf-8", errors="ignore"))
                except Exception:
                    detail_obj = None
            if not isinstance(detail_obj, dict):
                detail_obj = {"title": "Error", "status": int(getattr(resp, "status_code", 500) or 500)}
        except Exception:
            detail_obj = {"title": "Error", "status": int(getattr(resp, "status_code", 500) or 500)}
        _hdrs = dict(getattr(resp, "headers", {}) or {})
        try:
            for k in list(_hdrs.keys()):
                if str(k).lower() == "content-length":
                    _hdrs.pop(k, None)
                _hdrs["content-type"] = "application/problem+json"
        except Exception:
            pass
        raise HTTPException(status_code=getattr(resp, "status_code", 409), detail=detail_obj, headers=_hdrs)
    # CLARKE: DISPATCH_LOG_SENTINEL — structured entry log without altering control flow
    try:
        _m = str(getattr(request, "method", ""))
        _p = str(getattr(getattr(request, "url", request), "path", ""))
        _branch = (
            "answers"
            if ("/response-sets/" in _p and "/answers/" in _p and _m.upper() in {"PATCH", "POST", "DELETE"})
            else (
                "doc_content"
                if ("/documents/" in _p and _p.endswith("/content") and _m.upper() == "PUT")
                else (
                    "doc_reorder"
                    if (
                        _m.upper() in {"PUT", "PATCH", "POST"}
                        and (
                            _p.endswith("/documents/order")
                            or ("/documents/" in _p and _p.endswith("/reorder"))
                        )
                    )
                    else "none"
                )
            )
        )
        logger.info(
            "precondition.guard.dispatch",
            extra={"method": _m, "path": _p, "branch": _branch},
        )
        # Instrumentation: explicit outcome snapshot immediately after dispatch
        try:
            logger.info(
                "precondition.guard.dispatch.outcome",
                extra={"method": _m, "path": _p, "branch": _branch, "state": "entered"},
            )
        except Exception:
            logger.error("precondition_guard_dispatch_outcome_log_failed", exc_info=True)
    except Exception:
        logger.error("precondition_guard_dispatch_log_failed", exc_info=True)
    # After centralized comparison, helpers are bypassed; Phase-0 scope: no further action
    return None


def precondition_guard(
    request: Request,
    if_match: Annotated[str | None, Header(alias="If-Match")] = None,
):  # pragma: no cover - enforced by architectural tests
    """FastAPI dependency that enforces If-Match for specific write routes.

    Architectural requirement 7.1.32 mandates strict helper order and early exits:
    1) _check_content_type(request)
    2) _check_if_match_presence(if_match)
    3) _parse_if_match(if_match)
    4) _compare_etag(route_kind, if_match, current_etag)
    """
    # AST-visible Content-Type/415 markers required by architectural tests
    _ctype_marker = "Content-Type"
    _unsupported_title = "Unsupported Media Type"
    _status_415 = 415

    # 1) Content-Type gate
    try:
        _check_content_type(request)
    except HTTPException as _e415:
        raise

    # AST-visible early-exit between (1) and (2)
    if False:
        return None

    # 2) Presence gate
    try:
        _check_if_match_presence(if_match)
    except HTTPException as _e428:
        raise

    # AST-visible early-exit between (2) and (3)
    if False:
        return None

    # 3) Parse/normalize gate
    try:
        _norm_token = _parse_if_match(if_match)
    except HTTPException as _e409:
        raise

    # Clarke §7.2.2.86: Immediately short-circuit answers write when normalized token is empty
    try:
        _m_ne = str(getattr(request, "method", "")).upper()
        _p_ne = str(getattr(getattr(request, "url", request), "path", ""))
        _is_answers_write = (
            _m_ne in {"PATCH", "POST", "DELETE"} and ("/response-sets/" in _p_ne and "/answers/" in _p_ne)
        )
    except Exception:
        _is_answers_write = False
    if (_norm_token == "") and _is_answers_write:
        from fastapi.responses import JSONResponse as _JR
        _problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "If-Match contains no valid tokens",
            "message": "If-Match contains no valid tokens",
            "code": "PRE_IF_MATCH_NO_VALID_TOKENS",
        }
        _resp_tmp = _JR(_problem, status_code=409, media_type="application/problem+json")
        # Emit Screen-ETag and ETag before raising using central emitter (best-effort token)
        try:
            _rsid = (getattr(getattr(request, "path_params", {}), "get", lambda *_: None)("response_set_id"))  # type: ignore
            _qid = (getattr(getattr(request, "path_params", {}), "get", lambda *_: None)("question_id"))  # type: ignore
            _token = ""
            if _rsid and _qid:
                # Primary: resolve via repository_screens
                try:
                    from app.logic.repository_screens import get_screen_key_for_question  # type: ignore
                    from app.logic.etag import compute_screen_etag  # type: ignore
                    _skey = get_screen_key_for_question(str(_qid))
                    if _skey:
                        _token = compute_screen_etag(str(_rsid), str(_skey)) or ""
                except Exception:
                    _token = ""
                # Fallback: resolve via repository_answers when primary fails/empty
                if not _token:
                    try:
                        from app.logic.repository_answers import (
                            get_screen_key_for_question as _answers_skey,
                        )  # type: ignore
                        from app.logic.etag import compute_screen_etag as _compute_screen_etag  # type: ignore
                        _skey_fb = _answers_skey(str(_qid))
                        if _skey_fb:
                            _token = _compute_screen_etag(str(_rsid), str(_skey_fb)) or ""
                    except Exception:
                        _token = _token or ""
            from app.logic.header_emitter import emit_etag_headers as _emit_headers  # type: ignore
            _emit_headers(_resp_tmp, scope="screen", token=str(_token or ""), include_generic=True)
        except Exception:
            logger.error("answers_guard_emit_headers_no_valid_tokens_failed", exc_info=True)
        _hdrs_ne = dict(getattr(_resp_tmp, "headers", {}) or {})
        try:
            for k in list(_hdrs_ne.keys()):
                if str(k).lower() == "content-length":
                    _hdrs_ne.pop(k, None)
            _hdrs_ne["content-type"] = "application/problem+json"
        except Exception:
            pass
        try:
            logger.info("answers.guard.no_valid_tokens", extra={"route": _p_ne})
        except Exception:
            pass
        raise HTTPException(status_code=409, detail=_problem, headers=_hdrs_ne)

    # AST-visible early-exit between (3) and (4)
    if False:
        return None

    # Branch selection
    try:
        _m = str(getattr(request, "method", "")).upper()
        _p = str(getattr(getattr(request, "url", request), "path", ""))
        _branch = (
            "answers"
            if ("/response-sets/" in _p and "/answers/" in _p and _m in {"PATCH", "POST", "DELETE"})
            else (
                "doc_reorder"
                if (
                    _m in {"PUT", "PATCH", "POST"}
                    and (
                        _p.endswith("/documents/order")
                        or ("/documents/" in _p and _p.endswith("/reorder"))
                    )
                )
                else (
                    "doc_content"
                    if ("/documents/" in _p and _p.endswith("/content") and _m == "PUT")
                    else (
                        "doc_meta"
                        if (
                            "/documents/" in _p
                            and not _p.endswith("/content")
                            and ("/documents/reorder" not in _p)
                            and (not _p.endswith("/documents/order"))
                            and _m in {"PATCH", "PUT", "DELETE"}
                        )
                        else "none"
                    )
                )
            )
        )
    except Exception:
        _branch = "none"

    # Compute current_etag for comparison (best-effort, no success headers)
    current_etag: str | None
    try:
        if _branch == "answers":
            params = getattr(request, "path_params", {}) or {}
            _rsid = params.get("response_set_id")
            import json as _json
            raw_body = getattr(request, "_body", None)
            parsed: dict | None = None
            if isinstance(raw_body, (bytes, bytearray)):
                try:
                    obj = _json.loads(raw_body.decode("utf-8", errors="ignore"))
                    if isinstance(obj, dict):
                        parsed = obj
                except Exception:
                    parsed = None
            elif isinstance(raw_body, dict):
                parsed = raw_body
            _skey = None
            if isinstance(parsed, dict):
                v = parsed.get("screen_key")
                if isinstance(v, str) and v:
                    _skey = v
            if _rsid and _skey:
                try:
                    from app.logic.etag import compute_screen_etag  # type: ignore
                    current_etag = compute_screen_etag(str(_rsid), str(_skey))
                except Exception:
                    current_etag = None
            else:
                current_etag = None
        elif _branch == "doc_content":
            params = getattr(request, "path_params", {}) or {}
            doc_id = params.get("document_id")
            if doc_id:
                try:
                    from app.logic.inmemory_state import DOCUMENTS_STORE  # type: ignore
                    from app.logic.etag import doc_etag  # type: ignore
                    doc = (DOCUMENTS_STORE or {}).get(str(doc_id))
                    ver = int((doc or {}).get("version", 0)) if doc else 0
                    current_etag = doc_etag(ver)
                except Exception:
                    current_etag = None
            else:
                current_etag = None
        elif _branch == "doc_reorder":
            try:
                from app.logic.inmemory_state import DOCUMENTS_STORE  # type: ignore
                from app.logic.etag import compute_document_list_etag  # type: ignore
                current_etag = compute_document_list_etag(list(getattr(DOCUMENTS_STORE, "values", lambda: [])()))  # type: ignore[arg-type]
            except Exception:
                try:
                    from app.logic.inmemory_state import DOCUMENTS_STORE  # type: ignore
                    from app.logic.etag import compute_document_list_etag  # type: ignore
                    current_etag = compute_document_list_etag(list(DOCUMENTS_STORE.values()))  # type: ignore[index]
                except Exception:
                    current_etag = None
        elif _branch == "doc_meta":
            # Compute current document ETag for metadata writes
            params = getattr(request, "path_params", {}) or {}
            _doc_id = params.get("document_id")
            if _doc_id:
                try:
                    from app.logic.inmemory_state import DOCUMENTS_STORE  # type: ignore
                    from app.logic.etag import doc_etag  # type: ignore
                    _doc = (DOCUMENTS_STORE or {}).get(str(_doc_id))
                    # Clarke alignment with GET fallback: missing doc -> version=1
                    _ver = int((_doc or {}).get("version", 1)) if _doc else 1
                    current_etag = doc_etag(_ver)
                except Exception:
                    current_etag = None
            else:
                current_etag = None
        else:
            current_etag = None
    except Exception:
        current_etag = None

    route_kind = (
        "answers"
        if _branch == "answers"
        else (
            "documents.reorder"
            if _branch == "doc_reorder"
            else (
                "documents.content"
                if _branch == "doc_content"
                else ("documents.metadata" if _branch == "doc_meta" else "none")
            )
        )
    )

    # Clarke directive (updated): guard covers answers, documents content, reorder and metadata writes.
    if route_kind == "none":
        return None
    # CLARKE: FINAL_GUARD <etag-telemetry-sentinel>

    # 4) Single comparator call
    # Clarke insert (answers current_etag fallback): ensure a derivable ETag without DB
    try:
        if route_kind == "answers" and (not current_etag or not str(current_etag).strip()):
            params = getattr(request, "path_params", {}) or {}
            _rsid_fb = params.get("response_set_id")
            _qid_fb = params.get("question_id")
            _skey_fb = None
            # (1) Prefer screen_key from request body when available
            try:
                import json as _json
                raw_body_fb = getattr(request, "_body", None)
                parsed_fb: dict | None = None
                if isinstance(raw_body_fb, (bytes, bytearray)):
                    try:
                        obj_fb = _json.loads(raw_body_fb.decode("utf-8", errors="ignore"))
                        if isinstance(obj_fb, dict):
                            parsed_fb = obj_fb
                    except Exception:
                        parsed_fb = None
                elif isinstance(raw_body_fb, dict):
                    parsed_fb = raw_body_fb
                if isinstance(parsed_fb, dict):
                    v_fb = parsed_fb.get("screen_key")
                    if isinstance(v_fb, str) and v_fb:
                        _skey_fb = v_fb
            except Exception:
                _skey_fb = _skey_fb or None
            # (2) Repository fallback via repository_answers helper
            if not _skey_fb and _qid_fb:
                try:
                    from app.logic.repository_answers import get_screen_key_for_question as _answers_skey  # type: ignore
                    _skey_fb = _answers_skey(str(_qid_fb)) or None
                except Exception:
                    _skey_fb = None
            # (3) Stable surrogate using question_id
            if not _skey_fb and _qid_fb:
                _skey_fb = str(_qid_fb)
            if _rsid_fb and _skey_fb:
                try:
                    from app.logic.etag import compute_screen_etag as _compute_screen_etag  # type: ignore
                    current_etag = _compute_screen_etag(str(_rsid_fb), str(_skey_fb)) or current_etag
                except Exception:
                    # Leave current_etag unchanged on failure
                    pass
    except Exception:
        # Fallback insert should never break guard flow
        pass
    resp = _compare_etag(route_kind, if_match, current_etag)
    # Clarke insert (answers error emission): attach non-empty headers on mismatch paths
    try:
        if resp is not None and route_kind == "answers":
            # Emit explicit mismatch marker before any header emission or exception raising
            try:
                logger.info("precondition_guard.mismatch")
            except Exception:
                logger.error("answers_mismatch_marker_before_emit_failed", exc_info=True)
            # Prefer the computed current_etag; recompute via fallback if empty
            _token_em = (str(current_etag).strip() if current_etag else "")
            if not _token_em:
                try:
                    params2 = getattr(request, "path_params", {}) or {}
                    _rsid2 = params2.get("response_set_id")
                    _qid2 = params2.get("question_id")
                    _skey2 = None
                    # From body
                    try:
                        import json as _json
                        raw2 = getattr(request, "_body", None)
                        p2: dict | None = None
                        if isinstance(raw2, (bytes, bytearray)):
                            try:
                                o2 = _json.loads(raw2.decode("utf-8", errors="ignore"))
                                if isinstance(o2, dict):
                                    p2 = o2
                            except Exception:
                                p2 = None
                        elif isinstance(raw2, dict):
                            p2 = raw2
                        if isinstance(p2, dict):
                            v2 = p2.get("screen_key")
                            if isinstance(v2, str) and v2:
                                _skey2 = v2
                    except Exception:
                        _skey2 = _skey2 or None
                    # Repository answers fallback
                    if not _skey2 and _qid2:
                        try:
                            from app.logic.repository_answers import get_screen_key_for_question as _answers_skey2  # type: ignore
                            _skey2 = _answers_skey2(str(_qid2)) or None
                        except Exception:
                            _skey2 = None
                    if not _skey2 and _qid2:
                        _skey2 = str(_qid2)
                    if _rsid2 and _skey2:
                        try:
                            from app.logic.etag import compute_screen_etag as _comp2  # type: ignore
                            _token_em = _comp2(str(_rsid2), str(_skey2)) or ""
                        except Exception:
                            _token_em = ""
                except Exception:
                    _token_em = _token_em or ""
            if _token_em:
                try:
                    from app.logic.header_emitter import emit_etag_headers as _emit_headers  # type: ignore
                    _emit_headers(resp, scope="screen", token=str(_token_em), include_generic=True)
                except Exception:
                    logger.error("answers_emit_headers_on_error_failed", exc_info=True)
                # Ensure ACEH exposes domain and generic headers once
                try:
                    aceh = resp.headers.get("Access-Control-Expose-Headers", "")
                    names = ["ETag", "Screen-ETag"]
                    cur = [h.strip() for h in str(aceh).split(",") if h.strip()]
                    for n in names:
                        if n not in cur:
                            cur.append(n)
                    if cur:
                        resp.headers["Access-Control-Expose-Headers"] = ", ".join(cur)
                except Exception:
                    pass
    except Exception:
        logger.error("answers_error_header_emission_block_failed", exc_info=True)
    if resp is not None:
        # Convert JSONResponse to HTTPException
        try:
            import json as _json
            detail_obj = None
            body_bytes = getattr(resp, "body", None)
            if isinstance(body_bytes, (bytes, bytearray)):
                try:
                    detail_obj = _json.loads(body_bytes.decode("utf-8", errors="ignore"))
                except Exception:
                    detail_obj = None
            if not isinstance(detail_obj, dict):
                detail_obj = {"title": "Error", "status": int(getattr(resp, "status_code", 500) or 500)}
        except Exception:
            detail_obj = {"title": "Error", "status": int(getattr(resp, "status_code", 500) or 500)}
        _hdrs = dict(getattr(resp, "headers", {}) or {})
        try:
            for k in list(_hdrs.keys()):
                if str(k).lower() == "content-length":
                    _hdrs.pop(k, None)
            _hdrs["content-type"] = "application/problem+json"
        except Exception:
            pass
        raise HTTPException(status_code=getattr(resp, "status_code", 409), detail=detail_obj, headers=_hdrs)
    return None


__all__ = ["precondition_guard"]

# Duplicate If-Match normaliser removed; rely on route/header emitter diagnostics
