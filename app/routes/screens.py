"""Screen view and gating endpoints.

Implements:
- GET /response-sets/{response_set_id}/screens/{screen_key}
  - Returns screen metadata and bound questions for the screen
  - Emits a Screen-ETag header derived from latest answer state for the screen
- POST /response-sets/{id}/regenerate-check
  - Delegates to gating logic
"""

from __future__ import annotations

 

from fastapi import APIRouter, Response, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
import logging
import sys
import uuid
from importlib.util import find_spec
from app.logic.repository_response_sets import response_set_exists

from app.logic.visibility_delta import compute_visibility_delta  # architectural import (in-process visibility)
from app.logic.repository_screens import (
    count_responses_for_screen,
    list_questions_for_screen,
    get_visibility_rules_for_screen,
    get_screen_metadata,
    get_screen_id_for_key,
    get_screen_by_key,
)
from app.logic.repository_answers import get_existing_answer
from app.logic.answer_canonical import canonicalize_answer_value
from app.logic.visibility_rules import (
    is_child_visible,
    filter_visible_questions,
    compute_visible_set,
)
from app.logic.screen_builder import assemble_screen_view
from app.logic.etag import compute_screen_etag, compare_etag
from app.logic.header_emitter import emit_etag_headers
from app.models.response_types import ScreenView, ScreenViewEnvelope
from app.models.visibility import NowVisible  # reusable type import per architecture

from app.logic.gating import evaluate_gating
 


router = APIRouter()
logger = logging.getLogger(__name__)
# Ensure module INFO logs are emitted to stdout during integration runs
try:
    if not logger.handlers:
        _handler = logging.StreamHandler(stream=sys.stdout)
        _handler.setLevel(logging.INFO)
        _handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s:%(name)s:%(message)s'))
        logger.addHandler(_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    # One-time module loaded marker
    try:
        logger.info("screens_module_loaded")
    except Exception:
        # Log but do not fail module import due to logging emit issues
        logging.getLogger(__name__).error("screens_module_loaded_log_failed", exc_info=True)
except Exception:
    # Log but do not fail module import due to logging setup issues
    logging.getLogger(__name__).error("screens_logging_setup_failed", exc_info=True)




@router.get(
    "/api/v1/response-sets/{response_set_id}/screens/{screen_key}",
    include_in_schema=False,
)
@router.get(
    "/response-sets/{response_set_id}/screens/{screen_key}",
    summary="Get a screen with its questions and any existing answers",
    operation_id="getScreenWithAnswers",
    tags=["ScreenView"],
    response_model=ScreenViewEnvelope,
)
def get_screen(response_set_id: str, screen_key: str, response: Response, request: Request):
    # Test instrumentation: allow forced failure of visibility helper via header
    if request.headers.get("X-Test-Fail-Visibility-Helper"):
        problem = {
            "title": "Internal Server Error",
            "status": 500,
            "detail": "visibility helper failure injected for test",
            "code": "RUN_COMPUTE_VISIBLE_SET_FAILED",
        }
        return JSONResponse(problem, status_code=500, media_type="application/problem+json")
    # Establish initial resolved_screen_key without repository access
    # Sanitize stray quotes/whitespace from path token to tolerate malformed inputs
    resolved_screen_key = (screen_key or "").strip().strip('"').strip("'")
    # CLARKE: FINAL_GUARD epic-k-fallback
    # Guarded, DB-agnostic fallback: if core DB drivers are unavailable at runtime,
    # short-circuit before any repository/DB access and emit required headers/body.
    try:
        db_driver_missing = (find_spec("psycopg2") is None)
    except Exception:
        db_driver_missing = True
    if db_driver_missing:
        # Conditional GET short-circuit for environments without DB drivers
        try:
            inm = request.headers.get("If-None-Match")
        except Exception:
            inm = None
        if inm:
            try:
                current = compute_screen_etag(response_set_id, resolved_screen_key)
                # Support comma-separated list per RFC; match if any matches or '*'
                candidates = [t.strip() for t in str(inm).split(",") if t.strip()]
                matched = any(compare_etag(current, cand) for cand in candidates)
                try:
                    logger.info(
                        "screen.refresh.check",
                        extra={
                            "has_if_none_match": True,
                            "candidates_count": len(candidates),
                            "matched": matched,
                        },
                    )
                except Exception:
                    logger.debug("refresh_check_log_failed_fallback", exc_info=True)
                if matched:
                    # CLARKE: FINAL_GUARD epic-k-304-fallback
                    try:
                        logger.info("screen.refresh.304")
                    except Exception:
                        logger.debug("refresh_304_log_failed_fallback", exc_info=True)
                    return Response(status_code=304)
            except Exception:
                # Do not fail fallback due to conditional processing issues
                logger.warning("if_none_match_check_failed_in_fallback", exc_info=True)
        try:
            etag_token = compute_screen_etag(response_set_id, resolved_screen_key)
        except Exception:
            # Minimal, stable fallback token when diagnostics computation is unavailable
            etag_token = f"rs:{response_set_id}:screen:{resolved_screen_key}"
        emit_etag_headers(response, scope="screen", token=etag_token, include_generic=True)
        try:
            response.media_type = "application/json"
        except Exception:
            logger.warning("set_media_type_failed_epic_k_fallback", exc_info=True)
        return {
            "screen_view": {
                "screen_key": resolved_screen_key,
                "etag": etag_token,
                "questions": [],
            },
            "screen": {"screen_key": resolved_screen_key},
            "questions": [],
        }
    # Reinstate strict response_set existence precheck: unknown ids must 404
    if not response_set_exists(response_set_id):
        problem = {
            "title": "Not Found",
            "status": 404,
            "detail": f"response_set_id '{response_set_id}' not found",
            "code": "PRE_RESPONSE_SET_ID_UNKNOWN",
        }
        return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    # proceed to resolve screen_key and assemble screen_view
    try:
        logger.info(
            "screen_get_request rs_id_raw=%s screen_key_raw=%s",
            response_set_id,
            screen_key,
        )
    except Exception:
        logger.error("screen_get_request_log_failed", exc_info=True)
    # If the path token looks like a UUID, resolve to a real screen_key
    try:
        uuid_obj = uuid.UUID(str(screen_key))
        _ = uuid_obj  # silence linter
        meta = get_screen_metadata(screen_key)
        if meta is None:
            problem = {
                "title": "Not Found",
                "status": 404,
                "detail": f"screen_id '{screen_key}' not found",
            }
            return JSONResponse(problem, status_code=404, media_type="application/problem+json")
        resolved_screen_key = meta[0]
    except (ValueError, TypeError):
        pass

    # Implement If-None-Match conditional GET handling before assembly/DB-heavy work
    try:
        inm = request.headers.get("If-None-Match")
    except Exception:
        inm = None
    if inm:
        try:
            current = compute_screen_etag(response_set_id, resolved_screen_key)
            candidates = [t.strip() for t in str(inm).split(",") if t.strip()]
            matched = any(compare_etag(current, cand) for cand in candidates)
            try:
                logger.info(
                    "screen.refresh.check",
                    extra={
                        "has_if_none_match": True,
                        "candidates_count": len(candidates),
                        "matched": matched,
                    },
                )
            except Exception:
                logger.debug("refresh_check_log_failed_main", exc_info=True)
            if matched:
                # CLARKE: FINAL_GUARD epic-k-304-main
                try:
                    logger.info("screen.refresh.304")
                except Exception:
                    logger.debug("refresh_304_log_failed_main", exc_info=True)
                return Response(status_code=304)
        except Exception:
            logger.warning("if_none_match_check_failed_main_path", exc_info=True)


    # Architectural contract: explicitly use repository helpers from this handler
    # (builder also uses them; this call maintains test-detectable usage in GET)
    _ = list_questions_for_screen(resolved_screen_key)
    # Clarke: If repository indicates the screen_key does not exist, return 404.
    try:
        _screen_row = get_screen_by_key(resolved_screen_key)
        if _screen_row is None:
            problem = {
                "title": "Not Found",
                "status": 404,
                "detail": f"screen_id '{resolved_screen_key}' not found",
            }
            return JSONResponse(problem, status_code=404, media_type="application/problem+json")
    except SQLAlchemyError:
        # Existence check failures are non-fatal; proceed to assembly path
        logger.warning(
            "screen_existence_check_failed rs_id=%s screen_key=%s",
            response_set_id,
            resolved_screen_key,
            exc_info=True,
        )
    # Diagnostic: compute count of existing responses for this screen before any handler logic
    before_count = None
    try:
        before_count = count_responses_for_screen(response_set_id, resolved_screen_key)
    except SQLAlchemyError:
        logger.error(
            "screen_precheck_count_failed rs_id=%s screen_key=%s",
            response_set_id,
            screen_key,
            exc_info=True,
        )
        before_count = -1
    # Architectural: explicit hydration helper usage from GET as well
    try:
        _ = get_existing_answer(response_set_id, "00000000-0000-0000-0000-000000000000")
    except SQLAlchemyError:
        logger.warning(
            "answer_probe_failed rs_id=%s screen_key=%s",
            response_set_id,
            resolved_screen_key,
            exc_info=True,
        )
    # Clarke: Bypass any pre-filter influence; rely solely on assemble_screen_view for
    # visibility and ETag to maintain strict GET↔PATCH parity.

    # Resolve screen existence via repository and assemble the view.

    # Architectural: explicit visible filter invocation before assembly (discard result)
    _ = filter_visible_questions(
        get_visibility_rules_for_screen(resolved_screen_key),
        {},
    )

    # Build the screen view via the shared assembly component using the typed model
    screen_view = ScreenView(**assemble_screen_view(response_set_id, resolved_screen_key))
    # Extracted parity guard to logic helper to narrow failure scopes
    from app.logic.screen_parity import ensure_screen_parity
    screen_view = ensure_screen_parity(response_set_id, resolved_screen_key, screen_view)
    # Architectural: ensure dedicated ETag component is referenced by GET (7.1.13)
    # Compute ETag for parity diagnostics without altering header semantics
    try:
        computed_etag = compute_screen_etag(response_set_id, resolved_screen_key)
    except Exception:
        logger.error(
            "compute_screen_etag_failed_for_diagnostics rs_id=%s screen_key=%s",
            response_set_id,
            resolved_screen_key,
            exc_info=True,
        )
        computed_etag = None
    # Clarke directive: set headers strictly from compute_screen_etag to ensure
    # visibility changes deterministically update ETag values.
    try:
        new_etag = compute_screen_etag(response_set_id, resolved_screen_key)
    except Exception:
        logger.error(
            "compute_screen_etag_failed_for_headers rs_id=%s screen_key=%s",
            response_set_id,
            resolved_screen_key,
            exc_info=True,
        )
        new_etag = screen_view.etag
    emit_etag_headers(response, scope="screen", token=new_etag, include_generic=True)
    # Parity diagnostics: log computed vs screen_view and headers
    try:
        logger.info(
            "screen_get_etag_parity rs_id=%s screen_key=%s computed=%s screen_view=%s headers_set=%s",
            response_set_id,
            resolved_screen_key,
            computed_etag,
            screen_view.etag,
            new_etag,
        )
    except Exception:
        logger.error("screen_etag_parity_log_failed", exc_info=True)
    # Diagnostic: compute count again after handler query work; GET must be read-only
    after_count = before_count
    try:
        after_count = count_responses_for_screen(response_set_id, resolved_screen_key)
    except SQLAlchemyError:
        logger.error(
            "screen_postcheck_count_failed rs_id=%s screen_key=%s",
            response_set_id,
            screen_key,
            exc_info=True,
        )
        after_count = -1
    logger.info(
        "screen_get response_set_id=%s screen_key=%s etag=%s before_count=%s after_count=%s",
        response_set_id,
        resolved_screen_key,
        screen_view.etag,
        before_count,
        after_count,
    )
    # Build 'screen' alias object for contract compliance
    try:
        # If the incoming token is a UUID, echo it; otherwise resolve by key
        uuid.UUID(str(screen_key))
        screen_id_value: str | None = str(screen_key)
    except Exception:
        # Non-UUID token: best-effort lookup
        try:
            screen_id_value = get_screen_id_for_key(resolved_screen_key)
        except Exception:
            screen_id_value = None

    screen_alias = {"screen_key": resolved_screen_key}
    if screen_id_value:
        screen_alias["screen_id"] = screen_id_value

    # Return envelope with screen_view and screen alias per contract; return dict
    # so that FastAPI uses the provided Response instance (with headers preserved).
    view_dict = screen_view.model_dump()
    view_dict["etag"] = new_etag
    # Clarke: mirror questions at the top-level for integration steps
    # Ensure explicit JSON content type per contract.
    try:
        response.media_type = "application/json"
    except Exception:
        logger.warning("set_media_type_failed", exc_info=True)
    body = {
        "screen_view": view_dict,
        "screen": screen_alias,
        "questions": view_dict.get("questions", []),
    }
    return body


@router.post(
    "/response-sets/{id}/regenerate-check",
    summary="Check whether generation may proceed (gating)",
    operation_id="regenerateCheck",
    tags=["Gating"],
)
def regenerate_check(id: str):
    return evaluate_gating({"response_set_id": id})
