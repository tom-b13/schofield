"""Phase-0 ETag If-Match header normalisation helpers.

Provides a header-level parser that supports weak/strong equivalence, quoted
entity-tags, comma-separated lists, and multiple If-Match headers. This parser
returns a list of normalized opaque tokens for enforcement layers that need to
distinguish between "no valid tokens" and "valid but non-matching" conditions.

For backward compatibility, the token-level normaliser from ``app.logic.etag``
is re-exported as ``normalise_if_match``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Iterable, List

from app.logic.etag import normalize_if_match as normalise_if_match  # single-token normaliser


def _split_comma_aware(value: str) -> list[str]:
    """Split a header value on commas, respecting quoted segments.

    Returns a list of raw parts (whitespace-trimmed) without validation.
    """
    parts: list[str] = []
    buf: list[str] = []
    in_quote = False
    for ch in value:
        if ch == '"':
            in_quote = not in_quote
            buf.append(ch)
        elif ch == ',' and not in_quote:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf.clear()
        else:
            buf.append(ch)
    # Trailing buffer
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _iter_if_match_values(headers: Mapping[str, str] | None) -> Iterable[str]:
    """Yield raw If-Match header values from a mapping in a case-insensitive way.

    Accepts typical Starlette/FastAPI header mappings where keys are strings and
    values are strings. When the server layer consolidates multiple headers into
    a single comma-joined string, this function remains compatible.
    """
    if not headers:
        return []
    # Case-insensitive fetch
    values: list[str] = []
    for k, v in headers.items():
        if isinstance(k, str) and k.lower() == "if-match" and isinstance(v, str):
            values.append(v)
    return values


def normalize_if_match(headers: Mapping[str, str] | None) -> list[str]:
    """Return a list of normalized opaque entity-tags from If-Match headers.

    Rules:
    - Accept multiple If-Match header lines and comma-separated values.
    - Treat weak validators (W/"...") as equivalent to strong by stripping the
      prefix during normalisation.
    - Require quoted entity-tags; ignore malformed/whitespace-only tokens.
    - Return an empty list when no syntactically valid tokens are present.
    - Preserve original token semantics (do not de-duplicate or sort).
    """
    tokens: list[str] = []
    for raw in _iter_if_match_values(headers):
        if not isinstance(raw, str):
            continue
        s = raw.strip()
        if not s:
            continue
        # Split into potential entity-tags (quote-aware)
        for part in _split_comma_aware(s):
            t = part.strip()
            # Drop weak validator prefix if present (case-insensitive)
            if len(t) >= 2 and t[:2].upper() == "W/":
                t = t[2:].lstrip()
            # Expect quoted entity-tag
            if not (len(t) >= 2 and t.startswith('"') and t.endswith('"')):
                continue
            inner = t[1:-1]
            # Ignore empty or malformed quoted values
            if not inner or '"' in inner:
                continue
            tokens.append(inner.lower())
    return tokens


__all__ = ["normalise_if_match", "normalize_if_match"]
