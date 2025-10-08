"""Pure transform engine logic (Epic D service isolation).

No FastAPI/Starlette imports. Provides symbols referenced by route handlers.
"""

from __future__ import annotations

from typing import Iterable, List, Sequence, Mapping, Any
import re


def _canon_value(text: str) -> str:
    # Strip leading articles/phrases before canonicalisation
    raw = str(text or "")
    s = raw.strip()
    lower = s.lower()
    for prefix in ("on the ", "the ", "a ", "an "):
        if lower.startswith(prefix):
            s = s[len(prefix) :]
            break
    s = s.upper().replace("-", "_")
    s = re.sub(r"[^A-Z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "VALUE"


def suggest_options(probe: dict | None = None) -> List[str]:
    """Return a deterministic list of canonical option values for a probe.

    Rules per Clarke tests:
    - "on the intranet OR [DETAILS]" -> ["INTRANET", "PLACEHOLDER:DETAILS"]
    - Freeform text -> canonicalised single value.
    - Bracketed token -> treated as placeholder-only option.
    """
    if not isinstance(probe, dict):
        return []
    raw = str(probe.get("raw_text", ""))
    # enum with placeholder
    if " OR [" in raw and raw.endswith("]"):
        # split on OR, left literal, right placeholder [KEY]
        left, _, right = raw.partition(" OR ")
        # left literal canonical value
        left_val = _canon_value(left)
        # right placeholder key inside [ ]
        m = re.search(r"\[\s*([A-Za-z0-9_\-\s]+)\s*\]", right)
        key = (m.group(1) if m else "DETAILS").strip()
        return [left_val, f"PLACEHOLDER:{_canon_value(key)}".replace("PLACEHOLDER:PLACEHOLDER:", "PLACEHOLDER:")]
    # pure placeholder
    if raw.startswith("[") and raw.endswith("]"):
        key = raw[1:-1].strip() or "VALUE"
        return [f"PLACEHOLDER:{_canon_value(key)}"]
    # freeform literal -> single canonical value
    if raw:
        return [_canon_value(raw)]
    return []


def preview_transforms(payload: dict | None = None) -> Sequence[str]:
    """Return a stable preview sequence for transforms.

    For input {literals:[..]}, return canonicalised values in given order.
    For {raw_text:"..."}, return a single canonical value.
    """
    if not isinstance(payload, dict):
        return []
    literals = payload.get("literals")
    if isinstance(literals, list) and literals:
        out: List[str] = []
        for item in literals:
            out.append(_canon_value(str(item)))
        return out
    raw = payload.get("raw_text")
    if isinstance(raw, str) and raw:
        return [_canon_value(raw)]
    return []


__all__ = ["suggest_options", "preview_transforms"]


def verify_probe(probe: Mapping[str, Any] | None) -> bool:
    """Lightweight structural guard for a probe/receipt object.

    Architectural placeholder to satisfy bind immutability guard wiring.
    """
    return isinstance(probe, dict) or probe is None
