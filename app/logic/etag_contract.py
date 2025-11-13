"""Shared ETag precondition contract utilities (Phase-0).

Provides normalisation and If-Match enforcement helpers that preserve legacy
token values while enabling deterministic comparison. Intended for use by
routes that must enforce optimistic concurrency preconditions.
"""

from __future__ import annotations

from fastapi import Response
from fastapi.responses import JSONResponse
import logging

from app.logic.etag import compare_etag, normalize_if_match as _norm_single  # type: ignore
from app.logic.header_emitter import (
    emit_etag_headers as _emit_etag_headers,
    emit_reorder_diagnostics as _emit_reorder_diag,
)

logger = logging.getLogger(__name__)


def enforce_if_match(
    if_match_header: str | None,
    current_etag: str,
    route_id: str,
) -> tuple[bool, JSONResponse | None]:
    """Enforce If-Match against the provided current_etag.

    Returns a tuple: (ok, response). On success, ok=True and response is None.
    On failure, ok=False and response is a JSONResponse with media_type
    'application/problem+json' and the correct historic status code (428
    for missing, 409 for mismatch/invalid, 412 for normalization error).
    """
    # Debug: capture raw and normalized token for structured logs (no behavior change)
    if_match_raw = None if if_match_header is None else str(if_match_header)
    try:
        # Phase-0: treat normalized If-Match as a single string token
        if_match_norm_token = _norm_single(if_match_header)
    except Exception:  # pragma: no cover
        logger.error("etag_normalise_failed_entry", exc_info=True)
        if_match_norm_token = ""
    current_str = None
    try:
        current_str = str(current_etag)
    except Exception:  # pragma: no cover
        logger.error("etag_current_str_cast_failed", exc_info=True)
        current_str = None

    # CLARKE: FINAL_GUARD etag-enforce-log
    def _log_enforce_decision(_outcome: str, _token: str | None) -> None:
        try:
            logger.info(
                "etag.enforce.decision",
                extra={
                    "policy": "strict",
                    "route_id": str(route_id),
                    "if_match_raw": if_match_raw,
                    "if_match_normalized": _token,
                    "current_etag": current_str,
                    "match_outcome": _outcome,
                },
            )
        except Exception:
            logger.error("etag_enforce_decision_log_failed", exc_info=True)

    # Missing header -> 428 Precondition Required
    if not if_match_header or not str(if_match_header).strip():
        # 428 Precondition Required with explicit problem code per Epic K
        problem = {
            "title": "Precondition Required",
            "status": 428,
            "detail": "If-Match header is required for this operation",
            "code": "PRE_IF_MATCH_MISSING",
            "message": "If-Match header is required for this operation",
        }
        # Ensure problem media type is explicit for callers that don't set it
        try:
            if "__media_type__" not in problem:
                problem["__media_type__"] = "application/problem+json"
        except Exception:
            pass
        # Instrumentation: log decision outcome before returning
        try:
            logger.info(
                "etag.if_match_decision",
                extra={
                    "outcome": "missing",
                    "if_match_raw": if_match_raw,
                    "if_match_norm": None,
                    "current": current_str,
                    "status": 428,
                },
            )
        except Exception:
            logger.error("etag_if_match_missing_log_failed", exc_info=True)
        _log_enforce_decision("missing", None)
        try:
            logger.info("error_handler.handle", extra={"code": problem.get("code")})
        except Exception:
            pass
        return False, JSONResponse(problem, status_code=428, media_type="application/problem+json")

    # Granular classification prior to comparison
    try:
        raw = str(if_match_header)
    except Exception:  # pragma: no cover
        raw = ""
    # (1) Invalid format: control characters only (quotes handled by normalizer)
    try:
        has_ctrl = any((ord(c) < 32 or ord(c) == 127) for c in raw)
        if has_ctrl:
            problem = {
                "title": "Precondition Failed",
                "status": 409,
                "detail": "If-Match header has invalid format",
                "code": "PRE_IF_MATCH_INVALID_FORMAT",
                "message": "If-Match header has invalid format",
            }
            try:
                if "__media_type__" not in problem:
                    problem["__media_type__"] = "application/problem+json"
            except Exception:
                pass
            try:
                logger.info(
                    "etag.if_match_decision",
                    extra={
                        "outcome": "invalid_format",
                        "if_match_raw": if_match_raw,
                        "if_match_norm": None,
                        "current": current_str,
                        "status": 409,
                    },
                )
            except Exception:
                logger.error("etag_if_match_invalid_format_log_failed", exc_info=True)
            _log_enforce_decision("invalid_format", None)
            try:
                logger.info("error_handler.handle", extra={"code": problem.get("code")})
            except Exception:
                pass
            return False, JSONResponse(problem, status_code=409, media_type="application/problem+json")
    except Exception:  # pragma: no cover
        logger.error("etag_invalid_format_check_failed", exc_info=True)

    # (2) Normalization: detect exceptions and empty-result (no valid tokens)
    try:
        # Recompute normalized token using single-token normalizer to catch exceptions explicitly
        norm_token_check = _norm_single(if_match_header)
    except Exception:
        logger.error("etag_normalise_failed_strict", exc_info=True)
        problem = {
            "title": "Precondition Failed",
            "status": 412,
            "detail": "If-Match normalization error",
            "code": "RUN_IF_MATCH_NORMALIZATION_ERROR",
            "message": "If-Match normalization error",
        }
        try:
            if "__media_type__" not in problem:
                problem["__media_type__"] = "application/problem+json"
        except Exception:
            pass
        _log_enforce_decision("normalization_error", None)
        try:
            logger.info("error_handler.handle", extra={"code": problem.get("code")})
        except Exception:
            pass
        return False, JSONResponse(problem, status_code=412, media_type="application/problem+json")
    if not norm_token_check:
        problem = {
            "title": "Precondition Required",
            "status": 409,
            "detail": "If-Match contains no valid tokens",
            "code": "PRE_IF_MATCH_NO_VALID_TOKENS",
            "message": "If-Match contains no valid tokens",
        }
        try:
            if "__media_type__" not in problem:
                problem["__media_type__"] = "application/problem+json"
        except Exception:
            pass
        try:
            logger.info(
                "etag.if_match_decision",
                extra={
                    "outcome": "no_valid_tokens",
                    "if_match_raw": if_match_raw,
                    "if_match_norm": norm_token_check,
                    "current": current_str,
                    "status": 409,
                },
            )
        except Exception:
            logger.error("etag_if_match_no_tokens_log_failed", exc_info=True)
        _log_enforce_decision("no_valid_tokens", norm_token_check)
        # Ensure 'code' exists before returning (pre-return guard)
        if "code" not in problem:
            problem["code"] = "PRE_IF_MATCH_NO_VALID_TOKENS"
        resp = JSONResponse(problem, status_code=409, media_type="application/problem+json")
        try:
            logger.info("error_handler.handle", extra={"code": problem.get("code")})
        except Exception:
            pass
        # CLARKE: DIAG_EMIT 88C4-DOCS — attach reorder diagnostics when applicable
        try:
            # Heuristic: document list ETag is a 40-char hex digest (no quotes)
            cet = str(current_etag or "")
            is_doc_list = len(cet) == 40 and all(ch in "0123456789abcdef" for ch in cet.lower())
            if is_doc_list:
                _emit_reorder_diag(resp, cet, str(norm_token_check))
        except Exception:
            logger.error("etag_diag_emit_no_tokens_failed", exc_info=True)
        return False, resp

    # Compare using public comparator which applies canonical normalisation
    # Clarke change: treat missing/empty current_etag as mismatch before compare
    try:
        if if_match_norm_token == "*":
            matched = True
        else:
            if not current_str or not str(current_etag).strip():
                matched = False
            else:
                matched = compare_etag(current_etag, if_match_header)
    except Exception:
        logger.error("etag_compare_failed", exc_info=True)
        matched = False
    # Debug: log decision outcome before returning
    try:
        logger.info(
            "etag.if_match_decision",
            extra={
                "outcome": "pass" if matched else "mismatch",
                "if_match_raw": if_match_raw,
                "if_match_norm": if_match_norm_token,
                "current": current_str,
                "status": 200 if matched else 409,
            },
        )
        # Clarke instrumentation: structured enforcement decision with route_id
        logger.info(
            "etag.enforce.decision",
            extra={
                "route_id": str(route_id),
                "if_match_normalized": if_match_norm_token,
                "current_etag": current_str,
                "match_outcome": "pass" if matched else "mismatch",
            },
        )
    except Exception:
        logger.error("etag_if_match_outcome_log_failed", exc_info=True)

    # Clarke instrumentation: log compare inputs immediately before mismatch handling
    try:
        logger.info(
            "etag.enforce.decision",
            extra={
                "route_id": str(route_id),
                "if_match_normalized": if_match_norm_token,
                "current_etag": current_str,
                "match_outcome": "pass" if matched else "mismatch",
            },
        )
    except Exception:
        logger.error("etag_enforce_pre_mismatch_log_failed", exc_info=True)
    if not matched:
        # Conflict semantics for autosave answers and 412 mapping for documents.* per Clarke
        is_documents = False
        try:
            is_documents = str(route_id).startswith("documents.")
        except Exception:
            is_documents = False
        status_code = 412 if is_documents else 409
        problem = {
            "title": "Precondition Failed" if is_documents else "Conflict",
            "status": status_code,
            "detail": "If-Match does not match current ETag",
            "code": "PRE_IF_MATCH_ETAG_MISMATCH",
            "message": "If-Match does not match current ETag",
        }
        try:
            if "__media_type__" not in problem:
                problem["__media_type__"] = "application/problem+json"
        except Exception:
            pass
        _log_enforce_decision("mismatch", if_match_norm_token)
        # Ensure 'code' exists before returning (pre-return guard)
        if "code" not in problem:
            problem["code"] = "PRE_IF_MATCH_ETAG_MISMATCH"
        resp = JSONResponse(problem, status_code=status_code, media_type="application/problem+json")
        # Structured error handler marker and mismatch label for harness observability
        try:
            logger.info("error_handler.handle", extra={"code": problem.get("code")})
        except Exception:
            pass
        try:
            # Emit the canonical mismatch marker used by the harness when guard is bypassed
            logger.info("precondition_guard.mismatch")
        except Exception:
            pass
        # CLARKE: For documents.* routes, attach diagnostics headers explicitly
        try:
            if is_documents:
                _emit_reorder_diag(
                    resp,
                    str(current_etag or ""),
                    (str(if_match_norm_token).strip() if if_match_norm_token else ""),
                )
        except Exception:
            logger.error("etag_diag_emit_mismatch_failed", exc_info=True)
        # Heuristic: retain legacy diagnostics for list tokens even outside documents.*
        try:
            cet = str(current_etag or "")
            is_doc_list = len(cet) == 40 and all(ch in "0123456789abcdef" for ch in cet.lower())
            if not is_documents and is_doc_list:
                _emit_reorder_diag(resp, cet, str(if_match_norm_token))
        except Exception:
            logger.error("etag_diag_emit_mismatch_heuristic_failed", exc_info=True)
        return False, resp

    _log_enforce_decision("pass", if_match_norm_token)
    return True, None

# Instrumentation wrapper: emit a consolidated 'etag.enforce' telemetry event
# after each enforcement attempt without changing functional outcomes.
try:
    _enforce_impl = enforce_if_match  # keep reference to original implementation

    def enforce_if_match(  # type: ignore[override]
        if_match_header: str | None, current_etag: str, route_id: str
    ) -> tuple[bool, JSONResponse | None]:
        ok, resp = _enforce_impl(if_match_header, current_etag, route_id)
        try:
            norm = _norm_single(if_match_header)
        except Exception:  # pragma: no cover
            norm = None
        try:
            logger.info(
                "etag.enforce",
                extra={
                    "matched": bool(ok),
                    "normalized_if_match": norm,
                    "route_id": str(route_id),
                },
            )
        except Exception:  # pragma: no cover
            logger.error("etag_enforce_telemetry_log_failed", exc_info=True)
        return ok, resp
except Exception:  # pragma: no cover
    # In case rebinding fails (e.g., due to restricted environments), keep original
    pass

# Convenience proxy to expose diagnostics emission via this contract module
def emit_reorder_diagnostics(response: Response, list_etag: str, if_match_normalized: str) -> None:
    try:
        _emit_reorder_diag(response, list_etag, if_match_normalized)
    except Exception:  # pragma: no cover
        logger.error("emit_reorder_diagnostics_proxy_failed", exc_info=True)


def emit_headers(response: Response, scope: str, etag: str, include_generic: bool) -> None:
    """Emit ETag headers with extended structured logging for parity verification.

    Deterministic fallback placement: created wrapper in etag_contract since
    the canonical emitter lives in header_emitter. Delegates emission to the
    shared helper and adds non-invasive logs. No behavior change.
    """
    # Emit headers via the shared helper (no behavior change)
    try:
        _emit_etag_headers(response, scope=scope, token=etag, include_generic=include_generic)
    except Exception:  # pragma: no cover
        logger.error("emit_headers_delegate_failed", exc_info=True)
    # Structured instrumentation: include scope, header names chosen, and If-Match (normalized) if available
    try:
        domain_header = None
        try:
            # Import locally to avoid circular import at module load
            from app.logic.header_emitter import SCOPE_TO_HEADER  # type: ignore

            domain_header = SCOPE_TO_HEADER.get(scope)
        except Exception:
            domain_header = None
        # Extract normalized If-Match if present on response request context (best-effort only)
        if_match_norm = None
        try:
            # Some frameworks attach request to response; guard access
            request = getattr(response, "request", None)
            if request is not None:
                raw = request.headers.get("If-Match")  # type: ignore[attr-defined]
                if_match_norm = normalise_if_match(raw)
        except Exception:
            if_match_norm = None
        # Emit canonical telemetry event after headers are written
        logger.info(
            "etag.emit",
            extra={
                "scope": scope,
                "domain_header": domain_header,
                "include_generic": bool(include_generic),
                "if_match_norm": if_match_norm,
                "etag_token": str(etag),
            },
        )
    except Exception:
        logger.error("emit_headers_instrumentation_failed", exc_info=True)


__all__ = ["enforce_if_match", "emit_headers", "emit_reorder_diagnostics"]
