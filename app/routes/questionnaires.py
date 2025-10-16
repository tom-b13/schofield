"""Questionnaire import/export and metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, Response
from fastapi.responses import JSONResponse

from app.logic.csv_io import build_export_csv, parse_import_csv
from app.logic.repository_questionnaires import (
    get_questionnaire_metadata,
    questionnaire_exists,
)


router = APIRouter()


@router.get(
    "/api/v1/questionnaires/{id}",
    include_in_schema=False,
)
@router.get(
    "/questionnaires/{id}",
    summary="Get questionnaire metadata and screens index (no questions)",
    operation_id="getQuestionnaire",
    tags=["Questionnaires"],
)
def get_questionnaire(id: str):
    meta = get_questionnaire_metadata(id)
    if not meta:
        problem = {"title": "Questionnaire not found", "status": 404}
        return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    name, description = meta
    return {"questionnaire_id": id, "name": name, "description": description, "screens": []}


@router.post(
    "/questionnaires/import",
    summary="Import questionnaire CSV (v1.0)",
    operation_id="importQuestionnaireCsv",
    tags=["Import"],
)
def import_questionnaire(csv_export: bytes = Body(..., media_type="text/csv")):
    result = parse_import_csv(csv_export)
    return result


@router.get(
    "/questionnaires/{id}/export",
    summary="Export questionnaire CSV (v1.0)",
    operation_id="exportQuestionnaireCsv",
    tags=["Export"],
)
def export_questionnaire(id: str):
    # Existence check
    exists = questionnaire_exists(id)
    if not exists:
        problem = {"title": "Questionnaire not found", "status": 404}
        return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    data = build_export_csv(id)
    resp = Response(content=data, media_type="text/csv; charset=utf-8")
    resp.headers["ETag"] = str(hash(data))
    return resp
