"""FastAPI application package init for EPIC-A artifacts.

This package intentionally keeps a minimal surface area for this epic:
- Configuration loading helpers live in `app.config`.
- Database bootstrap and migration utilities live under `app.db`.

No web routes are defined as EPIC-A focuses on data model and migrations.
"""

__all__ = [
    "config",
]

