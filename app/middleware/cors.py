"""CORS configuration helpers (Epic K).

Provides a small utility for applying CORS with required exposed headers.
No diagnostics are added here; keep this focused on configuration only.
"""

from __future__ import annotations

from typing import Iterable
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


# Domain and generic ETag headers that must be exposed to browsers
EXPOSE_HEADERS: list[str] = [
    "ETag",
    "Screen-ETag",
    "Question-ETag",
    "Document-ETag",
    "Questionnaire-ETag",
]


def apply_cors(app: FastAPI, *, origins: Iterable[str] | None = None) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origins or ["*"]),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        # Explicitly expose the domain and generic ETag headers
        expose_headers=EXPOSE_HEADERS,
    )


__all__ = ["apply_cors", "EXPOSE_HEADERS"]
