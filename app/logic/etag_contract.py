"""Shared ETag precondition contract utilities (Phase-0).

Provides normalisation and If-Match enforcement helpers that preserve legacy
token values while enabling deterministic comparison. Intended for use by
routes that must enforce optimistic concurrency preconditions.
"""

from __future__ import annotations

from typing import Tuple
from fastapi import Response
import logging

from app.logic.etag import compare_etag
from app.logic.etag import normalize_if_match as normalise_if_match
from app.logic.header_emitter import emit_etag_headers as _emit_etag_headers

logger = logging.getLogger(__name__)


def enforce_if_match(
    if_match_header: str | None,
    current_etag: str,
    allow_wildcard: bool = True,
) -> tuple[bool, int, dict]:
    """Enforce If-Match against the provided current_etag.

    Returns a tuple: (ok, status_code, problem_json). On success, ok=True and
    status_code is 200 with an empty problem object. On failure, ok=False and
    status_code is 428 (missing) or 409 (mismatch) with a problem+json body
    describing the error.
    """
    # Debug: capture raw and normalized tokens for structured logs (no behavior change)
    if_match_raw = None if if_match_header is None else str(if_match_header)
    try:
        if_match_norm = normalise_if_match(if_match_header)
    except Exception:  # pragma: no cover
        logger.error("etag_normalise_failed_entry", exc_info=True)
        if_match_norm = if_match_raw
    current_str = None
    try:
        current_str = str(current_etag)
    except Exception:  # pragma: no cover
        logger.error("etag_current_str_cast_failed", exc_info=True)
        current_str = None

    # CLARKE: FINAL_GUARD etag-enforce-log
    def _log_enforce_decision(_outcome: str, _tokens) -> None:
        try:
            logger.info(
                "etag.enforce.decision",
                extra={
                    "policy": "strict",
                    "if_match_raw": if_match_raw,
                    "if_match_tokens": _tokens,
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
        }
        # Instrumentation: log decision outcome before returning
        try:
            logger.info(
                "etag.if_match_decision",
                extra={
                    "outcome": "missing",
                    "if_match_raw": if_match_raw,
                    "if_match_norm": if_match_norm,
                    "current": current_str,
                    "status": 428,
                },
            )
        except Exception:
            logger.error("etag_if_match_missing_log_failed", exc_info=True)
        _log_enforce_decision("missing", if_match_norm)
        return False, 428, problem

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
                "status": 412,
                "detail": "If-Match header has invalid format",
                "code": "PRE_IF_MATCH_INVALID_FORMAT",
            }
            try:
                logger.info(
                    "etag.if_match_decision",
                    extra={
                        "outcome": "invalid_format",
                        "if_match_raw": if_match_raw,
                        "if_match_norm": None,
                        "current": current_str,
                        "status": 412,
                    },
                )
            except Exception:
                logger.error("etag_if_match_invalid_format_log_failed", exc_info=True)
            _log_enforce_decision("invalid_format", None)
            return False, 412, problem
    except Exception:  # pragma: no cover
        logger.error("etag_invalid_format_check_failed", exc_info=True)

    # (2) Normalization: get normalized token(s); handle empty-results versus mismatch
    try:
        token = normalise_if_match(if_match_header)
    except Exception:
        logger.error("etag_normalise_failed_strict", exc_info=True)
        problem = {
            "title": "Precondition Failed",
            "status": 412,
            "detail": "If-Match normalization error",
            "code": "RUN_IF_MATCH_NORMALIZATION_ERROR",
        }
        _log_enforce_decision("normalization_error", None)
        return False, 412, problem
    # Treat the presence of any syntactically valid token as non-empty tokens list
    has_tokens = bool(token)
    if not has_tokens:
        # Normalized-empty: present header but yielded no valid tokens — 409 NO_VALID_TOKENS
        problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "If-Match does not match current ETag",
            "code": "PRE_IF_MATCH_NO_VALID_TOKENS",
        }
        try:
            logger.info(
                "etag.if_match_decision",
                extra={
                    "outcome": "normalized_empty",
                    "if_match_raw": if_match_raw,
                    "if_match_token": token,
                    "current": current_str,
                    "status": 409,
                },
            )
        except Exception:
            logger.error("etag_if_match_no_tokens_log_failed", exc_info=True)
        _log_enforce_decision("normalized_empty", token)
        return False, 409, problem

    # CLARKE: FINAL_GUARD ENFORCE_COMPARE_PROBE
    # Log normalized incoming/current tokens immediately before comparison to
    # confirm normalization and parity behaviour.
    try:
        incoming_norm = normalise_if_match(if_match_header)
    except Exception:
        incoming_norm = None
    try:
        current_norm = normalise_if_match(current_etag)
    except Exception:
        current_norm = None
    try:
        logger.info(
            "etag.enforce.compare",
            extra={
                "incoming_norm": incoming_norm,
                "current_norm": current_norm,
            },
        )
    except Exception:  # pragma: no cover
        logger.error("etag_enforce_compare_probe_log_failed", exc_info=True)
    # Plain-text token log for easier grepping in default formatters
    try:
        logger.info(
            "etag.enforce.compare.tokens incoming_norm=%s current_norm=%s",
            incoming_norm,
            current_norm,
        )
    except Exception:  # pragma: no cover
        logger.error("etag_enforce_compare_tokens_log_failed", exc_info=True)

    # Compare: string-based normalized equality; honor wildcard
    try:
        if allow_wildcard and token == "*":
            matched = True
        else:
            curr_token = normalise_if_match(current_etag)
            matched = bool(token) and (token == curr_token)
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
                "if_match_norm": if_match_norm,
                "current": current_str,
                "status": 200 if matched else 409,
            },
        )
    except Exception:
        logger.error("etag_if_match_outcome_log_failed", exc_info=True)

    if not matched:
        # 409 Conflict semantics for autosave answers per Clarke contract
        # Non-empty tokens that do not match current_etag → ETAG_MISMATCH
        problem = {
            "title": "Conflict",
            "status": 409,
            "detail": "If-Match does not match current ETag",
            "code": "PRE_IF_MATCH_ETAG_MISMATCH",
        }
        # Emit explicit token log on mismatch for postmortem correlation
        try:
            # Recompute normalized tokens defensively in case upstream probe failed
            incoming_norm_mm = None
            current_norm_mm = None
            try:
                incoming_norm_mm = normalise_if_match(if_match_header)
            except Exception:
                incoming_norm_mm = None
            try:
                current_norm_mm = normalise_if_match(current_etag)
            except Exception:
                current_norm_mm = None
            logger.info(
                "etag.if_match.mismatch.tokens incoming_norm=%s current_norm=%s",
                incoming_norm_mm,
                current_norm_mm,
            )
        except Exception:  # pragma: no cover
            logger.error("etag_if_match_mismatch_tokens_log_failed", exc_info=True)
        _log_enforce_decision("mismatch", if_match_norm)
        return False, 409, problem

    _log_enforce_decision("pass", if_match_norm)
    return True, 200, {}


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
        logger.info(
            "etag.emit_headers",
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


__all__ = ["enforce_if_match", "emit_headers"]
