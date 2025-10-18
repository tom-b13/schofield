"""Questionnaire import/export and metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, Response
from fastapi.responses import JSONResponse
import logging
import csv
import io

from app.logic.csv_io import parse_import_csv
from app.logic.header_emitter import emit_etag_headers, SCOPE_TO_HEADER
from app.logic.etag import compute_questionnaire_etag_for_authoring
from app.logic.repository_questionnaires import (
    get_questionnaire_metadata,
    questionnaire_exists,
    list_questions_for_questionnaire_export,
)


router = APIRouter()
logger = logging.getLogger(__name__)


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
    # Sanitize stray quotes/whitespace from path token before lookups
    id = (id or "").strip().strip('"').strip("'")
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
    "/api/v1/questionnaires/{id}/export",
    include_in_schema=False,
)
@router.get(
    "/questionnaires/{id}/export",
    summary="Export questionnaire CSV (v1.0)",
    operation_id="exportQuestionnaireCsv",
    tags=["Export"],
)
def export_questionnaire(id: str):
    # Existence check (with input sanitization to tolerate malformed path tokens)
    id = (id or "").strip().strip('"').strip("'")
    exists = questionnaire_exists(id)
    if not exists:
        problem = {"title": "Questionnaire not found", "status": 404}
        return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    # Build legacy CSV (Phase-0 parity): exact 3-column header and rows
    rows = list(list_questions_for_questionnaire_export(id))
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator='\n')
    # Header: exact legacy 3-column contract
    writer.writerow(["question_id", "question_text", "answer_kind"])
    for r in rows:
        writer.writerow([
            str(r.get("question_id", "")),
            str(r.get("question_text", "")),
            str(r.get("answer_kind", "")),
        ])
    data = buf.getvalue().encode("utf-8")
    resp = Response(content=data, media_type="text/csv; charset=utf-8")
    # Compute and emit ETag headers defensively; ensure both Questionnaire-ETag and ETag exist.
    try:
        q_etag = compute_questionnaire_etag_for_authoring(id)
    except Exception:
        q_etag = f"questionnaire:{id}"
    try:
        emit_etag_headers(resp, scope="questionnaire", token=q_etag, include_generic=True)
    except Exception:
        # Do not bypass central emitter with direct header assignment; log the fault
        logger.error("emit_etag_headers_failed", exc_info=True)
    try:
        logger.info(
            "export_questionnaire",
            extra={
                "path": f"/questionnaires/{id}/export",
                "questionnaire_id": id,
                "status": 200,
                "etag": resp.headers.get("ETag"),
                "questionnaire_etag": resp.headers.get(SCOPE_TO_HEADER["questionnaire"]),
            },
        )
    except Exception:
        pass
    return resp
