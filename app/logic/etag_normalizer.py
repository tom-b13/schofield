"""ETag/If-Match normaliser re-export.

Single-source normalisation lives in :mod:`app.logic.etag`.
This module intentionally re-exports only the public alias to satisfy
architectural constraints enforcing one implementation across the app/ tree.
"""

from __future__ import annotations

from app.logic.etag import normalize_if_match as normalise_if_match

__all__ = ["normalise_if_match"]
