"""Questionnaire import/export and metadata endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Body, Response, UploadFile, File, Request
from fastapi.responses import JSONResponse
import logging
import csv
import io

from app.logic.csv_io import parse_import_csv, build_export_csv
from app.logic.header_emitter import emit_etag_headers, SCOPE_TO_HEADER
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
async def import_questionnaire(
    request: Request,
    file: UploadFile | None = File(None),
    csv_export: bytes | None = Body(None, media_type="text/csv"),
):
    data: bytes
    source: str
    if file is not None:
        source = "multipart"
        data = file.file.read() if hasattr(file, "file") else (file.read() or b"")  # type: ignore[attr-defined]
    elif csv_export is not None:
        source = "raw"
        data = csv_export
    else:
        # Fallback: accept raw request body (e.g., text/plain or text/csv without Body binding)
        source = "raw"
        data = await request.body()

    # Pre-parse diagnostics: size and first-line preview (non-throwing)
    size_bytes = len(data)
    try:
        first_line = (data.split(b"\n", 1)[0] if data else b"").decode("utf-8", errors="ignore")
    except Exception:
        first_line = ""
    try:
        logger.info(
            "import_questionnaire_request",
            extra={
                "path": "/questionnaires/import",
                "source": source,
                "size_bytes": size_bytes,
                "first_line_preview": first_line[:120],
            },
        )
    except Exception:
        # Logging must never interfere with import behaviour
        pass

    # Parse with instrumentation; preserve existing semantics on failure
    try:
        result = parse_import_csv(data)
    except Exception as exc:
        try:
            logger.error(
                "import_questionnaire_failed",
                extra={
                    "path": "/questionnaires/import",
                    "source": source,
                    "size_bytes": size_bytes,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
                exc_info=True,
            )
        except Exception:
            pass
        raise

    # Post-parse success diagnostics: approximate row count (header excluded if present)
    try:
        line_count = data.count(b"\n") + (1 if (data and not data.endswith(b"\n")) else 0)
        approx_rows = max(0, line_count - 1)
        logger.info(
            "import_questionnaire_success",
            extra={
                "path": "/questionnaires/import",
                "source": source,
                "size_bytes": size_bytes,
                "approx_rows": approx_rows,
            },
        )
    except Exception:
        pass

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
    # Existence check relaxed for Phase-0: always return CSV (header-only when unknown)
    id = (id or "").strip().strip('"').strip("'")
    exists = questionnaire_exists(id)
    # Build legacy CSV (Phase-0 parity): exact 3-column header and rows via central builder
    # CLARKE: FINAL_GUARD epic-k-export-fallback — harden export to degrade gracefully on SQL errors
    try:
        data = build_export_csv(id, rows=[]) if not exists else build_export_csv(id)
    except Exception as exc:
        # Fallback to header-only CSV on any failure (e.g., sqlite3.OperationalError)
        try:
            data = build_export_csv(id, rows=[])
        except Exception:
            # Absolute last resort: minimal header-only CSV without builder
            _buf = io.StringIO()
            writer = csv.writer(_buf)
            writer.writerow(["question_id", "question_text", "placeholder_code"])  # legacy header
            data = _buf.getvalue()
        try:
            logger.error(
                "export_questionnaire_fallback",
                extra={
                    "path": f"/questionnaires/{id}/export",
                    "questionnaire_id": id,
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                },
                exc_info=True,
            )
        except Exception:
            pass
    resp = Response(content=data, media_type="text/csv; charset=utf-8")
    # Compute and emit ETag headers defensively; ensure both Questionnaire-ETag and ETag exist.
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


# CSV-suffixed aliases delegating to the same export logic
@router.get(
    "/api/v1/questionnaires/{id}/export.csv",
    include_in_schema=False,
)
@router.get(
    "/questionnaires/{id}/export.csv",
    include_in_schema=False,
)
def export_questionnaire_csv(id: str):
    return export_questionnaire(id)
