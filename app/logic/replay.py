"""Neutral replay adapter for write handlers.

Encapsulates token extraction, payload hashing, and in-memory replay storage
for write-path endpoints without surfacing policy-specific identifiers to
route modules.
"""

from __future__ import annotations

from typing import Any, Optional, Tuple
import hashlib
import json

from fastapi import Request, Response

# Internal helpers and state stores (may use legacy request replay paths)
from app.logic.request_replay import (
    check_replay_before_write as _legacy_check,
    store_replay_after_success as _legacy_store,
)
from app.logic.inmemory_state import (
    ANSWERS_IDEMPOTENT_RESULTS as _ANSWERS_REPLAY,
    ANSWERS_LAST_SUCCESS as _ANSWERS_LAST_SUCCESS,
)


def _extract_token(request: Request) -> Optional[str]:
    """Extract client-provided token from headers (case-insensitive)."""
    try:
        for k, v in request.headers.items():
            if isinstance(k, str) and k.lower() == "idempotency-key":
                sv = str(v).strip()
                if sv:
                    return sv
    except Exception:
        token = request.headers.get("Idempotency-Key")
        if isinstance(token, str):
            token = token.strip()
            if token:
                return token
    return None


def _stable_body_hash(payload: dict | None) -> str:
    """Compute a stable hash for the payload dict."""
    try:
        body_json = json.dumps(payload or {}, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body_json.encode("utf-8")).hexdigest()
    except Exception:
        return ""


def maybe_replay(
    request: Request,
    response: Response,
    resource_key: Tuple[str, str] | None,
    payload: dict | None,
) -> Optional[dict]:
    """Return a previously stored body if a matching replay entry exists.

    Uses a composite key of (token, response_set_id, question_id, body_hash)
    when possible; otherwise falls back to legacy request-level replay.
    """
    token = _extract_token(request)
    body_hash = _stable_body_hash(payload or {})
    try:
        rs_id, q_id = resource_key if resource_key else ("", "")
    except Exception:
        rs_id, q_id = "", ""

    if token:
        # 1) Try token-based composite replay first
        replay_key = f"{token}:{rs_id}:{q_id}:{body_hash}"
        stored = _ANSWERS_REPLAY.get(replay_key)
        if stored:
            et = stored.get("etag")
            se = stored.get("screen_etag") or et
            if et:
                response.headers["ETag"] = et
            if se:
                response.headers["Screen-ETag"] = se
            body = stored.get("body")
            if isinstance(body, dict):
                return body
        # 2) Token-based miss: do not fall back to tokenless replay; require a real write
    else:
        # No token provided: attempt tokenless last-success replay only
        tokenless_key = f"{rs_id}:{q_id}:{body_hash}"
        stored = _ANSWERS_LAST_SUCCESS.get(tokenless_key)
        if stored:
            et = stored.get("etag")
            se = stored.get("screen_etag") or et
            if et:
                response.headers["ETag"] = et
            if se:
                response.headers["Screen-ETag"] = se
            body = stored.get("body")
            if isinstance(body, dict):
                return body

    # Fallback to legacy route+method keyed storage
    return _legacy_check(request, response, None)


def store_after_success(
    request: Request,
    response: Response,
    body: dict,
    resource_key: Tuple[str, str] | None,
    payload: dict | None,
) -> None:
    """Persist response to support future replays using token+resource+payload."""
    token = _extract_token(request)
    body_hash = _stable_body_hash(payload or {})
    try:
        rs_id, q_id = resource_key if resource_key else ("", "")
    except Exception:
        rs_id, q_id = "", ""

    if token:
        replay_key = f"{token}:{rs_id}:{q_id}:{body_hash}"
        try:
            _ANSWERS_REPLAY[replay_key] = {
                "body": body,
                "etag": response.headers.get("ETag"),
                "screen_etag": response.headers.get("Screen-ETag"),
            }
        except Exception:
            pass

    # Always write tokenless last-success entry alongside any token-based store
    try:
        tokenless_key = f"{rs_id}:{q_id}:{body_hash}"
        _ANSWERS_LAST_SUCCESS[tokenless_key] = {
            "body": body,
            "etag": response.headers.get("ETag"),
            "screen_etag": response.headers.get("Screen-ETag"),
        }
    except Exception:
        pass

    # Always persist via legacy helper as well for broader parity
    try:
        _legacy_store(request, response, body)
    except Exception:
        return


def store_replay_after_success(request: Request, response: Response, body: dict) -> None:
    """Compatibility wrapper to persist replay data after a successful write.

    Mirrors Clarke's expected helper signature. Delegates to the legacy
    request-level store to ensure subsequent maybe_replay can short-circuit
    on identical Idempotency-Key without risking route failures.
    """
    try:
        from app.logic.request_replay import store_replay_after_success as _legacy_store

        _legacy_store(request, response, body)
    except Exception:
        # Never impact the request lifecycle if replay storage fails
        return
