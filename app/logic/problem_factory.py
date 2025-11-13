"""Centralised construction of problem+json payloads for precondition errors.

Provides helpers that return dicts with PRE_* codes to avoid embedding
string literals in route modules. Kept minimal per Epic K Phase-0.
"""

from __future__ import annotations

from typing import Dict
import logging


logger = logging.getLogger(__name__)


def problem_pre_request_content_type_unsupported() -> Dict[str, object]:
    """Return a 415 problem indicating Content-Type must be application/json."""
    problem = {
        "title": "Unsupported Media Type",
        "status": 415,
        "detail": "Content-Type must be application/json",
        "message": "Content-Type must be application/json",
        "code": "PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED",
    }
    try:
        logger.info("error_handler.handle", extra={"code": problem.get("code")})
    except Exception:
        pass
    return problem


def problem_pre_if_match_missing() -> Dict[str, object]:
    """Return a 428 problem indicating If-Match header is required and missing."""
    problem = {
        "title": "Precondition Required",
        "status": 428,
        "detail": "If-Match header is required",
        "message": "If-Match header is required",
        "code": "PRE_IF_MATCH_MISSING",
    }
    try:
        logger.info("error_handler.handle", extra={"code": problem.get("code")})
    except Exception:
        pass
    return problem


def problem_pre_if_match_no_valid_tokens() -> Dict[str, object]:
    """Return a 409 problem indicating If-Match contained no valid tokens."""
    problem = {
        "title": "Conflict",
        "status": 409,
        "detail": "If-Match contains no valid tokens",
        "message": "If-Match contains no valid tokens",
        "code": "PRE_IF_MATCH_NO_VALID_TOKENS",
    }
    try:
        logger.info("error_handler.handle", extra={"code": problem.get("code")})
    except Exception:
        pass
    return problem


def problem_pre_query_param_invalid() -> Dict[str, object]:
    """Return a 409 problem for unexpected query parameters present."""
    problem = {
        "title": "Invalid Request",
        "status": 409,
        "detail": "Unexpected query parameters present",
        "code": "PRE_QUERY_PARAM_INVALID",
        "message": "Unexpected query parameters present",
    }
    try:
        logger.info("error_handler.handle", extra={"code": problem.get("code")})
    except Exception:
        pass
    return problem


def problem_pre_path_param_invalid() -> Dict[str, object]:
    """Return a 409 problem for invalid path parameter characters."""
    problem = {
        "title": "Invalid Request",
        "status": 409,
        "detail": "Path parameter contains invalid characters",
        "code": "PRE_PATH_PARAM_INVALID",
        "message": "Path parameter contains invalid characters",
    }
    try:
        logger.info("error_handler.handle", extra={"code": problem.get("code")})
    except Exception:
        pass
    return problem


def problem_pre_resource_not_found() -> Dict[str, object]:
    """Return a 409 problem for not found sentinel during prevalidation."""
    problem = {
        "title": "Not Found",
        "status": 409,
        "detail": "question not found",
        "code": "PRE_RESOURCE_NOT_FOUND",
        "message": "question not found",
    }
    try:
        logger.info("error_handler.handle", extra={"code": problem.get("code")})
    except Exception:
        pass
    return problem
