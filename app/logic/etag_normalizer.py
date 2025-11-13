"""Re-export of the single shared If-Match normaliser.

This module intentionally defines no functions. Architectural rule 7.1.1
requires a single source of truth under ``app.logic.etag``. Existing call
sites that import from ``app.logic.etag_normalizer`` continue to function
via this alias.
"""

from app.logic.etag import normalize_if_match as normalise_if_match  # noqa: F401

__all__ = ["normalise_if_match"]
