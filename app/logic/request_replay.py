"""Generic request replay helper for write handlers.

This module centralises the optional replay behaviour used to return the
same response for repeat submissions that include a stable client token.

Routes should call these helpers and must not reference header names or
storage directly. This keeps route modules free from policy-specific
identifiers required by architectural tests.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import Request, Response

from app.logic.inmemory_state import ANSWERS_IDEMPOTENT_RESULTS as _STORE


def _get_token(request: Request) -> Optional[str]:
    """Extract and normalise the client-provided replay token from headers.

    The concrete header name and normalisation rules are intentionally
    encapsulated here to keep route handlers free of policy details.
    """
    # Robust, case-insensitive extraction for 'Idempotency-Key'
    try:
        for k, v in request.headers.items():
            if isinstance(k, str) and k.lower() == "idempotency-key":
                token = str(v).strip()
                if token:
                    return token
    except Exception:
        # Best-effort: fall back to direct get (Starlette headers are case-insensitive)
        token = request.headers.get("Idempotency-Key")
        if isinstance(token, str):
            token = token.strip()
            if token:
                return token
    return None


def check_replay_before_write(
    request: Request, response: Response, current_etag: str | None
) -> Optional[dict]:
    """Return a previously stored response body when a replay token matches.

    If a stored entry is found, response headers are set from the stored
    values and the body dict is returned for the route to short-circuit.
    When no match exists, returns None.
    """
    token = _get_token(request)
    if not token:
        return None
    # Clarke: composite key to avoid collisions across routes
    method = (request.method or "").upper()
    path = getattr(getattr(request, "url", None), "path", "") or ""
    composite_key = f"{token}:{method}:{path}"
    stored = _STORE.get(composite_key)
    if not stored:
        return None
    stored_etag = stored.get("etag")
    stored_screen_etag = stored.get("screen_etag") or stored_etag or current_etag
    if stored_etag:
        response.headers["ETag"] = stored_etag  # strong entity tag for parity
    if stored_screen_etag:
        response.headers["Screen-ETag"] = stored_screen_etag
    body = stored.get("body")
    if isinstance(body, dict):
        return body
    return None


def store_replay_after_success(request: Request, response: Response, body: dict) -> None:
    """Persist successful response details for potential replay.

    Stores body and relevant headers keyed by the replay token, when present.
    Failures in this function must not affect the caller.
    """
    token = _get_token(request)
    if not token:
        return
    try:
        method = (request.method or "").upper()
        path = getattr(getattr(request, "url", None), "path", "") or ""
        composite_key = f"{token}:{method}:{path}"
        _STORE[composite_key] = {
            "body": body,
            "etag": response.headers.get("ETag"),
            "screen_etag": response.headers.get("Screen-ETag"),
        }
    except Exception:
        # Never let storage errors impact the request lifecycle
        return
