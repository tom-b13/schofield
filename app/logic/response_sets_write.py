"""Helpers for Response Sets write operations (architectural extraction)."""

from __future__ import annotations

from datetime import datetime, timezone


def format_created_at(dt: datetime | None = None) -> str:
    """Format an RFC3339 UTC timestamp with trailing 'Z'."""
    base = (dt or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    return base.replace("+00:00", "Z")


def make_etag(rs_id: str) -> str:
    """Construct a weak ETag token for response set identifiers."""
    return f'W/"rs-{rs_id}"'


__all__ = ["format_created_at", "make_etag"]

