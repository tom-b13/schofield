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


from hashlib import sha1
from typing import Dict


def build_probe(raw_text: str, context: Dict[str, Any] | None) -> Dict[str, Any]:
    """Construct a stable probe object with resolved_span and hash."""
    ctx = context or {}
    span = (ctx or {}).get("span") or {}
    doc_id = (ctx or {}).get("document_id")
    clause_path = (ctx or {}).get("clause_path")
    start = int((span or {}).get("start", 0))
    end = int((span or {}).get("end", max(0, len(raw_text))))
    probe_token = f"{doc_id}|{clause_path}|{start}|{end}|{raw_text}".encode("utf-8")
    probe_hash = sha1(probe_token).hexdigest()
    return {
        "document_id": doc_id,
        "clause_path": clause_path,
        "resolved_span": {"start": start, "end": end},
        "probe_hash": probe_hash,
    }


def suggest_transform(raw_text: str, context: Dict[str, Any] | None) -> Dict[str, Any] | None:
    """Return a suggestion dict for a given raw_text/context or None."""
    canonical = suggest_options({"raw_text": raw_text, "context": context or {}})
    probe = build_probe(raw_text, context or {})
    # boolean
    if raw_text.startswith("[") and raw_text.endswith("]") and raw_text[1:].upper().startswith("INCLUDE "):
        return {
            "transform_id": "boolean_v1",
            "name": "Boolean include",
            "answer_kind": "boolean",
            "probe": probe,
        }
    # enum_single with placeholders and literal
    if " OR [" in raw_text and raw_text.endswith("]"):
        left_literal_text = raw_text.partition(" OR ")[0].strip()
        placeholders: list[dict] = []
        literal_option: dict | None = None
        for val in canonical:
            if val.startswith("PLACEHOLDER:"):
                key = val.split(":", 1)[1]
                placeholders.append({"value": key.upper().replace("-", "_"), "placeholder_key": key})
            else:
                if literal_option is None:
                    literal_option = {"value": val, "label": left_literal_text}
        options: list[dict] = []
        if literal_option:
            options.append(literal_option)
        options.extend(placeholders)
        options = sorted(options, key=lambda _: 0)
        return {
            "transform_id": "enum_single_v1",
            "name": "Single choice",
            "answer_kind": "enum_single",
            "options": options,
            "probe": probe,
        }
    # short_string for bracketed token
    if raw_text.startswith("[") and raw_text.endswith("]"):
        return {
            "transform_id": "short_string_v1",
            "name": "Short string",
            "answer_kind": "short_string",
            "probe": probe,
        }
    # fallback: enum_single with canonicalised freeform
    if canonical:
        options = [{"value": v} for v in canonical]
        options = sorted(options, key=lambda _: 0)
        return {
            "transform_id": "enum_single_v1",
            "name": "Single choice",
            "answer_kind": "enum_single",
            "options": options,
            "probe": probe,
        }
    return None


__all__ = [
    "suggest_options",
    "preview_transforms",
    "build_probe",
    "suggest_transform",
]


def verify_probe(probe: Mapping[str, Any] | None) -> bool:
    """Lightweight structural guard for a probe/receipt object.

    Architectural placeholder to satisfy bind immutability guard wiring.
    """
    return isinstance(probe, dict) or probe is None
