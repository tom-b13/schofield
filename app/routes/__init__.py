"""APIRouter registration for Questionnaire Service."""

from __future__ import annotations

from fastapi import APIRouter

from app.routes.answers import router as answers_router
from app.routes.documents import router as documents_router
from app.routes.questionnaires import router as questionnaires_router
from app.routes.screens import router as screens_router
# Epic D skeleton routers (Clarke): transforms and placeholders
try:
    from app.routes.transforms import router as transforms_router  # type: ignore
except ImportError:
    transforms_router = None  # type: ignore
try:
    from app.routes.placeholders import router as placeholders_router  # type: ignore
except ImportError:
    placeholders_router = None  # type: ignore
try:
    from app.routes.bindings_purge import router as bindings_purge_router  # type: ignore
except ImportError:
    bindings_purge_router = None  # type: ignore

api_router = APIRouter()
api_router.include_router(questionnaires_router, tags=["Questionnaires", "Import", "Export"])  # tags applied per-operation
api_router.include_router(screens_router, tags=["ScreenView", "Gating"])  # tags applied per-operation
api_router.include_router(answers_router, tags=["Autosave"])  # tags applied per-operation
api_router.include_router(documents_router, tags=["Documents"])  # Epic C skeleton routes
if transforms_router is not None:
    api_router.include_router(transforms_router, tags=["Transforms"])  # Epic D skeleton
if placeholders_router is not None:
    api_router.include_router(placeholders_router, tags=["Placeholders", "Bindings"])  # Epic D skeleton
if bindings_purge_router is not None:
    api_router.include_router(bindings_purge_router, tags=["Bindings", "Documents"])  # Epic D skeleton

__all__ = ["api_router"]
