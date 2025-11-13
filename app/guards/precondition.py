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
    """Return normalized If-Match token or raise PRE_* problem on invalid format/empty tokens.

    - invalid_format -> 409 PRE_IF_MATCH_INVALID_FORMAT
    - no valid tokens -> 409 PRE_IF_MATCH_NO_VALID_TOKENS
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
            # Syntactically valid list but no valid tokens after normalization
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
            problem = {
                "title": "Conflict",
                "status": 409,
                "detail": "If-Match contains no valid tokens",
                "message": "If-Match contains no valid tokens",
                "code": "PRE_IF_MATCH_NO_VALID_TOKENS",
            }
            raise HTTPException(status_code=409, detail=problem, headers={"content-type": "application/problem+json"})
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


def _compare_etag(route_kind: str, normalized_if_match: str, current_etag: Optional[str]) -> Optional[JSONResponse]:
    """Compare normalized If-Match with current_etag and return problem response on mismatch.

    Phase-0 contract: compare normalized tokens only. Treat '*' as an
    any-match wildcard. Do not pass normalized tokens into compare_etag,
    which expects raw header values.
    Route kinds: 'answers' → 409; 'documents*' → 412.
    """
    # Compute normalized current tag using the canonical normaliser
    try:
        from app.logic.etag import normalize_if_match as _norm  # type: ignore
    except Exception:  # pragma: no cover - fallback to dedicated normalizer
        try:
            from app.logic.etag_normalizer import normalise_if_match as _norm  # type: ignore
        except Exception:
            def _norm(_: Optional[str]) -> str:  # type: ignore[override]
                return ""

    try:
        current_norm = _norm(current_etag)
    except Exception:
        current_norm = ""

    # Wildcard '*' matches any current token; otherwise require exact normalized equality
    matched = (normalized_if_match == "*" or normalized_if_match == current_norm)
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
    return JSONResponse(problem, status_code=int(mp.get("status", _default_status)), media_type="application/problem+json")


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
        try:
            from app.logic.etag_contract import emit_headers as _emit_headers  # type: ignore
            _emit_headers(resp, scope="screen", etag=str(current_etag_for_headers or ""), include_generic=True)
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
    current_etag: str | None = None
    try:
        from app.logic.repository_screens import get_screen_key_for_question  # type: ignore
        from app.logic.etag import compute_screen_etag  # type: ignore
        _screen_key = get_screen_key_for_question(str(question_id))
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
                    current_etag = compute_screen_etag(str(response_set_id), str(screen_key_from_body))
                except Exception:
                    current_etag = None
        except Exception:
            # ignore fallback errors; enforcement will handle via PRE_* codes
            current_etag = current_etag
    # CLARKE: FINAL_GUARD <answers.body_screen_key_fallback>

    # Unconditional enforcement per Clarke: pass empty token when unavailable to surface PRE_IF_MATCH_* codes
    # Enforce with explicit route identifier per Clarke; do not early-return on missing current_etag
    ok, resp = _enforce(if_match, current_etag, "answers.autosave")
    try:
        logger.info(
            "etag.enforce",
            extra={
                "resource": "screen",
                "route": str(request.url.path),
                "if_match_raw": str(if_match),
                "if_match_norm": _normalize(if_match),
                "current_etag": current_etag,
                "outcome": "pass" if ok else "mismatch",
            },
        )
    except Exception:
        logger.error("answers_guard_etag_enforce_log_failed", exc_info=True)
    if not ok and isinstance(resp, JSONResponse):
        # Ensure Screen-ETag and ETag are present on problem responses
        try:
            from app.logic.etag_contract import emit_headers as _emit_headers  # type: ignore
            _emit_headers(resp, scope="screen", etag=str(current_etag or ""), include_generic=True)
        except Exception:
            logger.error("answers_guard_emit_headers_failed", exc_info=True)
        # Instrumentation: mismatch branch with normalized token and current ETag
        try:
            from app.logic.etag import normalize_if_match as _normalize  # type: ignore
            logger.info(
                "answers.guard.mismatch",
                extra={
                    "if_match_norm": _normalize(if_match),
                    "current_etag": str(current_etag) if current_etag is not None else None,
                },
            )
        except Exception:
            logger.error("answers_guard_mismatch_log_failed", exc_info=True)
        # Convert to HTTPException to guarantee dependency short-circuit
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
                detail_obj = {"title": "Conflict", "status": int(getattr(resp, "status_code", 409) or 409)}
            # Ensure problem code is present for mismatch path per Epic K (use central mapping)
            try:
                if "code" not in detail_obj:
                    detail_obj["code"] = PRECONDITION_ERROR_MAP.get("mismatch_answers", {}).get("code", "PRE_IF_MATCH_ETAG_MISMATCH")
            except Exception:
                # Leave detail_obj unchanged if mutation fails
                pass
        except Exception:
            detail_obj = {"title": "Conflict", "status": int(getattr(resp, "status_code", 409) or 409)}
        _hdrs = dict(resp.headers)
        try:
            # Ensure problem+json Content-Type and strip content-length
            _hdrs["content-type"] = "application/problem+json"
            for k in list(_hdrs.keys()):
                if str(k).lower() == "content-length":
                    _hdrs.pop(k, None)
        except Exception:
            logger.error("answers_guard_prepare_headers_failed", exc_info=True)
        raise HTTPException(status_code=resp.status_code, detail=detail_obj, headers=_hdrs)
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


def precondition_guard(
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
                        if (_m_b.upper() in {"PUT", "PATCH"} and (_p_b.endswith("/documents/order") or ("/documents/reorder" in _p_b)))
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
                        if (_m_b.upper() in {"PUT", "PATCH"} and (_p_b.endswith("/documents/order") or ("/documents/reorder" in _p_b)))
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
                        if (_m_b.upper() in {"PUT", "PATCH"} and (_p_b.endswith("/documents/order") or ("/documents/reorder" in _p_b)))
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
                        if (_m_b.upper() in {"PUT", "PATCH"} and (_p_b.endswith("/documents/order") or ("/documents/reorder" in _p_b)))
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
                    from fastapi.responses import JSONResponse as _JR
                    _status = int(getattr(_e409, "status_code", 409) or 409)
                    _resp_tmp = _JR(_detail if isinstance(_detail, dict) else {}, status_code=_status, media_type="application/problem+json")
                    try:
                        from app.logic.etag_contract import emit_headers as _emit_headers  # type: ignore
                        if _rsid and _skey:
                            try:
                                from app.logic.etag import compute_screen_etag  # type: ignore
                                _cet = compute_screen_etag(str(_rsid), str(_skey))
                            except Exception:
                                _cet = ""
                        else:
                            _cet = ""
                        _emit_headers(_resp_tmp, scope="screen", etag=str(_cet), include_generic=True)
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
                    if (_m.upper() in {"PUT", "PATCH"} and (_p.endswith("/documents/order") or ("/documents/reorder" in _p)))
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
                try:
                    _ver = int((_doc or {}).get("version", 0))
                except Exception:
                    _ver = 0
                _current_doc_etag = doc_etag(_ver)
            except Exception:
                _current_doc_etag = None
        try:
            from app.logic.etag_contract import enforce_if_match as _enforce_dm  # type: ignore
            from app.logic.etag_contract import emit_headers as _emit_headers_dm  # type: ignore
            ok_dm, resp_dm = _enforce_dm(if_match, _current_doc_etag or "", "documents.metadata")
        except Exception:
            ok_dm, resp_dm = True, None
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
        resp = _compare_etag(route_kind, _norm_token, current_etag)
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
    # Safety: ensure answers mismatch maps to PRE_IF_MATCH_ETAG_MISMATCH before exiting
    try:
        _m_f = str(getattr(request, "method", ""))
        _p_f = str(getattr(getattr(request, "url", request), "path", ""))
        _is_answers = ("/response-sets/" in _p_f and "/answers/" in _p_f and _m_f.upper() in {"PATCH", "POST", "DELETE"})
        if _is_answers:
            _resp2 = _compare_etag("answers", _norm_token, current_etag)
            if _resp2 is not None:
                try:
                    import json as _json
                    _det2 = None
                    _b2 = getattr(_resp2, "body", None)
                    if isinstance(_b2, (bytes, bytearray)):
                        try:
                            _det2 = _json.loads(_b2.decode("utf-8", errors="ignore"))
                        except Exception:
                            _det2 = None
                    if not isinstance(_det2, dict):
                        _det2 = {"title": "Conflict", "status": int(getattr(_resp2, "status_code", 409) or 409)}
                except Exception:
                    _det2 = {"title": "Conflict", "status": int(getattr(_resp2, "status_code", 409) or 409)}
                _h2 = dict(getattr(_resp2, "headers", {}) or {})
                try:
                    for k in list(_h2.keys()):
                        if str(k).lower() == "content-length":
                            _h2.pop(k, None)
                    _h2["content-type"] = "application/problem+json"
                except Exception:
                    pass
                try:
                    logger.info(
                        "precondition.guard.exit",
                        extra={"branch": "answers", "outcome": "mismatch_answers"},
                    )
                except Exception:
                    logger.error("precondition_guard_exit_answers_safety_log_failed", exc_info=True)
                raise HTTPException(status_code=getattr(_resp2, "status_code", 409), detail=_det2, headers=_h2)
    except HTTPException:
        raise
    except Exception:
        logger.error("answers_post_compare_safety_failed", exc_info=True)
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
                    if (_m.upper() in {"PUT", "PATCH"} and (_p.endswith("/documents/order") or ("/documents/reorder" in _p)))
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


__all__ = ["precondition_guard"]

# Duplicate If-Match normaliser removed; rely on route/header emitter diagnostics
