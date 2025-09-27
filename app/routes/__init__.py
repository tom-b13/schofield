"""APIRouter registration for Questionnaire Service."""

from __future__ import annotations

from fastapi import APIRouter

from app.routes.answers import router as answers_router
from app.routes.questionnaires import router as questionnaires_router
from app.routes.screens import router as screens_router

api_router = APIRouter()
api_router.include_router(questionnaires_router, tags=["Questionnaires", "Import", "Export"])  # tags applied per-operation
api_router.include_router(screens_router, tags=["ScreenView", "Gating"])  # tags applied per-operation
api_router.include_router(answers_router, tags=["Autosave"])  # tags applied per-operation

__all__ = ["api_router"]
