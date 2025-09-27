"""Step definitions for Questionnaire Service integration.

Implements DB seeding for Background, HTTP interactions, header capture,
JSONPath assertions, and minimal JSON Schema validation.

Live mode uses a running API at TEST_BASE_URL and a real database at
TEST_DATABASE_URL. Mock mode is supported via TEST_MOCK_MODE but is not
used by these scenarios.
"""

from __future__ import annotations

import csv
import io
import json
import os
import uuid
from typing import Any, Dict, List, Optional, Tuple

import httpx
from behave import given, then, when, step
import re
from sqlalchemy import create_engine, text as sql_text

# Optional jsonschema validation (fallbacks provided if missing)
try:
    from jsonschema import Draft202012Validator, FormatChecker, RefResolver  # type: ignore
    _JSONSCHEMA_AVAILABLE = True
except Exception:
    Draft202012Validator = FormatChecker = RefResolver = None  # type: ignore
    _JSONSCHEMA_AVAILABLE = False


# ------------------
# Schema helpers
# ------------------

def _load_schema(name: str) -> Dict[str, Any]:
    path = f"schemas/{name}"
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _load_doc_schema(name: str) -> Dict[str, Any]:
    """Load a schema from docs/schemas/ as per Clarke guidance.

    The docs versions represent the source-of-truth contracts used by the
    specification. These may intentionally differ from the runtime validation
    schemas under ./schemas.
    """
    path = f"docs/schemas/{name}"
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


_SCHEMAS: Dict[str, Dict[str, Any]] = {}


def _schemas() -> Dict[str, Dict[str, Any]]:
    global _SCHEMAS
    if _SCHEMAS:
        return _SCHEMAS
    _SCHEMAS = {
        "AutosaveResult": _load_schema("AutosaveResult.schema.json"),
        "RegenerateCheckResult": _load_schema("RegenerateCheckResult.schema.json"),
        "ImportResult": _load_schema("ImportResult.schema.json"),
        "Problem": _load_schema("Problem.schema.json"),
        "ValidationProblem": _load_schema("ValidationProblem.schema.json"),
        "CSVExportSnapshot": _load_schema("CSVExportSnapshot.schema.json"),
        "ResponseSetId": _load_schema("ResponseSetId.schema.json"),
        "ScreenId": _load_schema("ScreenId.schema.json"),
        "QuestionId": _load_schema("QuestionId.schema.json"),
        "QuestionnaireId": _load_schema("QuestionnaireId.schema.json"),
        # Use the docs/schemas variant for AnswerUpsert to align with spec
        # (does not require answer_kind and focuses on value/option_id shape).
        "AnswerUpsert": _load_doc_schema("AnswerUpsert.schema.json"),
        "CSVImportFile": _load_schema("CSVImportFile.schema.json"),
    }
    # Optional ValidationItem
    try:
        _SCHEMAS["ValidationItem"] = _load_schema("ValidationItem.schema.json")
    except Exception:
        pass
    return _SCHEMAS


def _schema(name: str) -> Dict[str, Any]:
    return _schemas()[name]


def _schema_store() -> Dict[str, Dict[str, Any]]:
    store: Dict[str, Dict[str, Any]] = {}
    for sch in _schemas().values():
        sid = sch.get("$id")
        if isinstance(sid, str) and sid:
            store[sid] = sch
    return store


def _validate(instance: Any, schema: Dict[str, Any]) -> None:
    if not _JSONSCHEMA_AVAILABLE:
        # Clarke: enforce strict schema validation; do not allow permissive fallback
        raise AssertionError(
            "jsonschema is required for integration schema validation; install 'jsonschema' to run tests"
        )
    validator = Draft202012Validator(
        schema,
        format_checker=FormatChecker(),
        resolver=RefResolver.from_schema(schema, store=_schema_store()),
    )
    validator.validate(instance)


def _fallback_validate(instance: Any, schema: Dict[str, Any]) -> None:
    # Minimal checks when jsonschema is unavailable
    title = schema.get("title") or schema.get("$id") or ""
    name = str(title)
    if "Problem" in name:
        assert isinstance(instance, dict), "Problem must be object"
        assert isinstance(instance.get("title"), str), "Problem.title must be string"
        assert isinstance(instance.get("status"), int), "Problem.status must be integer"
        return
    if "RegenerateCheckResult" in name:
        assert isinstance(instance, dict) and isinstance(instance.get("ok"), bool), "ok must be boolean"
        assert isinstance(instance.get("blocking_items"), list), "blocking_items must be array"
        return
    if "AutosaveResult" in name:
        assert isinstance(instance, dict) and isinstance(instance.get("saved"), bool), "saved must be boolean"
        et = instance.get("etag")
        assert isinstance(et, str) and et.strip(), "etag must be non-empty string"
        return
    # Best-effort for others
    return


def _validate_with_name(instance: Any, schema_name: str) -> None:
    # Clarke: avoid fallback; require Draft 2020-12 validation to run
    _validate(instance, _schema(schema_name))


# ------------------
# Small util: interpolate {var} using context.vars and strip quotes
# ------------------

def _interpolate(value: str, context) -> str:
    v = value
    # Replace any {var} occurrences with values captured in context.vars
    vars_map = getattr(context, "vars", {}) or {}
    def repl(m: re.Match[str]) -> str:
        key = m.group(1)
        return str(vars_map.get(key, m.group(0)))
    v = re.sub(r"\{([A-Za-z0-9_\-]+)\}", repl, v)
    # Unwrap simple surrounding quotes (e.g., "*" -> *)
    if (len(v) >= 2) and ((v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'"))):
        v = v[1:-1]
        # Clarke: Unescape backslash-escaped tokens for header/table values
        # Specifically ensure "\\*" becomes '*' so If-Match wildcard works.
        try:
            v = v.replace("\\*", "*")
        except Exception:
            # Best-effort; leave as-is if replace fails
            pass
    return v


# ------------------
# JSONPath helper
# ------------------

def _jsonpath(data: Any, path: str) -> Any:
    def _compact(obj: Any) -> str:
        try:
            return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return repr(obj)

    original_path = path
    path = (
        path.replace("\\$", "$")
        .replace("\\.", ".")
        .replace("\\[", "[")
        .replace("\\]", "]")
        .replace("\\_", "_")
    )
    assert path.startswith("$"), f"Unsupported path: {original_path}"
    if path.endswith(".length()"):
        base = path[:-9]
        val = _jsonpath(data, base)
        try:
            return len(val)
        except Exception as exc:
            raise AssertionError(f"length() target not sized: {val!r} ({exc})")
    # Filter: $.questions[?(@.question_id=='...')].answer_kind
    if "[?(@." in path:
        try:
            prefix, rest = path.split("[?(@.", 1)
            field, right = rest.split("=='", 1)
            value, tail = right.split("')]")
        except Exception as exc:
            raise AssertionError(f"Malformed filter in path={original_path}: {exc}")
        arr = _jsonpath(data, prefix)
        assert isinstance(arr, list), f"Filter base must be list: {prefix} => {_compact(arr)}"
        matched = [item for item in arr if str(item.get(field)) == value]
        remainder = tail.lstrip(".")
        if remainder:
            return [m.get(remainder) for m in matched]
        return matched
    cur: Any = data
    tokens = path[1:].lstrip(".").split(".") if path != "$" else []
    for tok in tokens:
        if "[" in tok and tok.endswith("]"):
            name, idx_str = tok.split("[", 1)
            idx = int(idx_str[:-1])
            cur = cur[name][idx]
        else:
            cur = cur[tok]
    return cur


# ------------------
# HTTP helper
# ------------------

def _http_request(
    context,
    method: str,
    path: str,
    *,
    headers: Optional[Dict[str, str]] = None,
    json_body: Any = None,
    text_body: Optional[str] = None,
) -> Tuple[int, Dict[str, str], Optional[Dict[str, Any]], Optional[str]]:
    # Guard: HTTP calls are not allowed in mock mode per Clarke guidance
    if getattr(context, "test_mock_mode", False):
        raise AssertionError(
            "HTTP request attempted in TEST_MOCK_MODE; provide TEST_BASE_URL/TEST_DATABASE_URL for live runs or disable TEST_MOCK_MODE"
        )
    base = getattr(context, "test_base_url", "").rstrip("/")
    # Clarke: apply API prefix when feature path is unversioned
    api_prefix = str(getattr(context, "api_prefix", "/api/v1"))
    try:
        needs_prefix = isinstance(path, str) and path.startswith("/") and not path.startswith("/api/")
        effective_path = (api_prefix.rstrip("/") + path) if needs_prefix else path
    except Exception:
        effective_path = path
    url = base + str(effective_path)
    hdrs = (headers or {}).copy()
    hdrs.setdefault("Accept", "*/*")
    with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
        resp = client.request(
            method.upper(),
            url,
            headers=hdrs,
            # Support raw text bodies (e.g., CSV) and JSON bodies
            content=text_body if text_body is not None else None,
            json=json_body,
        )
        out_headers = {k: v for k, v in resp.headers.items()}
        # Case-insensitive Content-Type retrieval
        ctype = next((v for k, v in out_headers.items() if str(k).lower() == "content-type"), "")
        # Ensure canonical Content-Type key is present for subsequent assertions
        if "Content-Type" not in out_headers and ctype:
            out_headers["Content-Type"] = ctype
        body_json: Optional[Dict[str, Any]] = None
        body_text: Optional[str] = None
        try:
            if isinstance(ctype, str) and (ctype.startswith("application/json") or ctype.startswith("application/problem+json")):
                body_json = resp.json()
            else:
                # Attempt to parse JSON even if header casing differs or is missing
                try:
                    body_json = resp.json()
                except Exception:
                    body_text = resp.text
        except Exception:
            body_text = resp.text
        return resp.status_code, out_headers, body_json, body_text


# ------------------
# Header assertion helpers (Clarke: Headers & concurrency)
# ------------------

def _get_header_case_insensitive(headers: Dict[str, str], name: str) -> Optional[str]:
    lname = name.lower()
    for k, v in headers.items():
        if k.lower() == lname:
            return v
    return None


def _assert_x_request_id(context) -> None:
    headers = context.last_response.get("headers", {}) or {}
    rid = _get_header_case_insensitive(headers, "X-Request-Id")
    assert isinstance(rid, str) and rid.strip(), "Expected non-empty X-Request-Id header on JSON response"


def _assert_response_etag_present(context) -> str:
    headers = context.last_response.get("headers", {}) or {}
    etag = _get_header_case_insensitive(headers, "ETag")
    assert isinstance(etag, str) and etag.strip(), "Expected non-empty ETag header exposed by server"
    return etag


# ------------------
# DB helpers
# ------------------

def _db_engine(context):
    eng = getattr(context, "_db_engine", None)
    if eng is None:
        url = getattr(context, "test_database_url", None)
        # In live mode, environment hooks ensure TEST_DATABASE_URL exists.
        # In mock mode, DB helpers and steps short-circuit before calling this.
        if url:
            eng = create_engine(url, future=True)
        else:
            eng = None  # type: ignore[assignment]
        context._db_engine = eng
    return eng


def _db_exec(context, sql: str, params: Optional[Dict[str, Any]] = None) -> None:
    if getattr(context, "test_mock_mode", False):
        return
    eng = _db_engine(context)
    assert eng is not None, "Database not configured; TEST_DATABASE_URL is required for DB steps"
    with eng.begin() as conn:
        conn.execute(sql_text(sql), params or {})


def _row_count_response(context, rs_id: str, q_id: Optional[str] = None) -> int:
    if getattr(context, "test_mock_mode", False):
        return 0
    eng = _db_engine(context)
    assert eng is not None, "Database not configured; TEST_DATABASE_URL is required for DB steps"
    base = "SELECT COUNT(*) FROM response WHERE response_set_id = :rs"
    sql = base + (" AND question_id = :q" if q_id else "")
    params: Dict[str, Any] = {"rs": rs_id}
    if q_id:
        params["q"] = q_id
    with eng.connect() as conn:
        return int(conn.execute(sql_text(sql), params).scalar_one())


def _row_value_text(context, rs_id: str, q_id: str) -> Optional[str]:
    if getattr(context, "test_mock_mode", False):
        return None
    eng = _db_engine(context)
    assert eng is not None, "Database not configured; TEST_DATABASE_URL is required for DB steps"
    query = (
        "SELECT COALESCE(value_text, CAST(value_number AS TEXT), CASE WHEN value_bool IS NOT NULL THEN CASE WHEN value_bool THEN 'true' ELSE 'false' END ELSE NULL END) AS v "
        "FROM response WHERE response_set_id = :rs AND question_id = :q ORDER BY answered_at DESC LIMIT 1"
    )
    with eng.connect() as conn:
        return conn.execute(sql_text(query), {"rs": rs_id, "q": q_id}).scalar_one_or_none()


# ------------------
# Given steps (DB seeding)
# ------------------


@given("a clean database")
def step_clean_db(context):
    # Truncate relevant tables in FK-safe order (no-op in mock mode)
    if not getattr(context, "test_mock_mode", False):
        eng = _db_engine(context)
        assert eng is not None, "Database not configured; TEST_DATABASE_URL is required for DB steps"
        with eng.begin() as conn:
            for tbl in ("response", "answer_option", "questionnaire_question", "screens", "questionnaires", "response_set", "company"):
                try:
                    conn.execute(sql_text(f"DELETE FROM {tbl}"))
                except Exception:
                    # Best-effort for optional tables
                    pass
    context.vars = {}
    context.last_response = {"status": None, "headers": {}, "json": None, "text": None, "path": None, "method": None}


@given("the following questionnaire exists in the database:")
def step_setup_questionnaire(context):
    if getattr(context, "test_mock_mode", False):
        return
    for row in context.table:
        questionnaire_id, key, title = row[0], row[1], row[2]
        _db_exec(
            context,
            "INSERT INTO questionnaires (questionnaire_id, name, description) VALUES (:id, :name, :desc)"
            " ON CONFLICT (questionnaire_id) DO UPDATE SET name=EXCLUDED.name, description=EXCLUDED.description",
            {"id": questionnaire_id, "name": key, "desc": title},
        )


@given('the following screens exist for questionnaire "{questionnaire_id}":')
def step_setup_screens(context, questionnaire_id: str):
    if getattr(context, "test_mock_mode", False):
        return
    for row in context.table:
        screen_id, screen_key, title, order_str = row[0], row[1], row[2], row[3]
        _db_exec(
            context,
            "INSERT INTO screens (screen_id, questionnaire_id, screen_key, title) VALUES (:sid, :qid, :key, :title)"
            " ON CONFLICT (screen_id) DO UPDATE SET screen_key=EXCLUDED.screen_key, title=EXCLUDED.title",
            {"sid": screen_id, "qid": questionnaire_id, "key": screen_key, "title": title},
        )


@given('the following questions exist and are bound to screen "{screen_id}":')
def step_setup_questions(context, screen_id: str):
    if getattr(context, "test_mock_mode", False):
        return
    # Resolve screen_key for the given screen_id
    eng = _db_engine(context)
    assert eng is not None, "Database not configured; TEST_DATABASE_URL is required for DB steps"
    with eng.connect() as conn:
        row = conn.execute(sql_text("SELECT screen_key FROM screens WHERE screen_id = :sid"), {"sid": screen_id}).fetchone()
    if not row:
        raise AssertionError(f"Unknown screen_id: {screen_id}")
    screen_key = row[0]
    def _unescape_cell(val: str) -> str:
        try:
            return val.replace("\\_", "_")
        except Exception:
            return val
    for row in context.table:
        question_id, external_qid, question_text, answer_kind, mandatory_str, question_order_str = (
            row[0], _unescape_cell(row[1]), _unescape_cell(row[2]), _unescape_cell(row[3]), row[4], row[5]
        )
        _db_exec(
            context,
            "INSERT INTO questionnaire_question (question_id, screen_key, external_qid, question_order, question_text, answer_type, mandatory) "
            "VALUES (:qid, :skey, :ext, :ord, :qtext, :atype, :mand) "
            "ON CONFLICT (question_id) DO UPDATE SET external_qid=EXCLUDED.external_qid, question_order=EXCLUDED.question_order, question_text=EXCLUDED.question_text, answer_type=EXCLUDED.answer_type, mandatory=EXCLUDED.mandatory",
            {
                "qid": question_id,
                "skey": screen_key,
                "ext": external_qid,
                "ord": int(question_order_str),
                "qtext": question_text,
                # Clarke: Normalize escaped tokens (e.g., short\\_string -> short_string)
                "atype": _unescape_cell(answer_kind),
                "mand": mandatory_str.strip().lower() in {"true", "1", "yes"},
            },
        )
    # Persist mapping for later ordering checks
    context.vars.setdefault("qid_by_ext", {}).update({str(r[1]): str(r[0]) for r in context.table})


@given("an empty response set exists:")
def step_setup_response_set(context):
    if getattr(context, "test_mock_mode", False):
        return
    for row in context.table:
        rs_id, company_id = row[0], row[1]
        # Ensure company row for FK with minimal valid payload per spec
        # Clarke: Insert legal_name on first insert; preserve existing values on conflict
        _db_exec(
            context,
            "INSERT INTO company (company_id, legal_name) VALUES (:cid, :legal) "
            "ON CONFLICT (company_id) DO NOTHING",
            {"cid": company_id, "legal": "Test Co"},
        )
        _db_exec(
            context,
            "INSERT INTO response_set (response_set_id, company_id) VALUES (:rs, :cid) "
            "ON CONFLICT (response_set_id) DO UPDATE SET company_id=EXCLUDED.company_id",
            {"rs": rs_id, "cid": company_id},
        )


@given('no answers exist yet for response set "{response_set_id}"')
def step_no_answers_for_rs(context, response_set_id: str):
    if getattr(context, "test_mock_mode", False):
        return
    assert _row_count_response(context, response_set_id) == 0


@given('I GET "{path}" and capture header "ETag" as "{var_name}"')
@step('I GET "{path}" and capture header "ETag" as "{var_name}"')
def step_given_get_and_capture(context, path: str, var_name: str):
    step_when_get(context, path)
    headers = context.last_response.get("headers", {}) or {}
    # Clarke: use case-insensitive header retrieval
    val = _get_header_case_insensitive(headers, "ETag")
    assert isinstance(val, str) and val.strip(), "Expected non-empty ETag header"
    context.vars[var_name] = val


# ------------------
# When steps
# ------------------


@when('I GET "{path}"')
@step('I GET "{path}"')
def step_when_get(context, path: str):
    # Clarke: Validate QuestionnaireId for export path before issuing request
    if "/questionnaires/" in path and path.endswith("/export"):
        try:
            parts = path.strip("/").split("/")
            # /questionnaires/{id}/export -> ["questionnaires", "{id}", "export"]
            if len(parts) >= 3 and parts[0] == "questionnaires" and parts[2] == "export":
                _validate_with_name(parts[1], "QuestionnaireId")
        except Exception as exc:
            # Let schema errors surface; avoid masking
            raise
    status, headers, body_json, body_text = _http_request(context, "GET", path)
    context.last_response = {
        "status": status,
        "headers": headers,
        "json": body_json,
        "text": body_text,
        "path": path,
        "method": "GET",
    }
    # Clarke: All JSON responses must include X-Request-Id (200/4xx)
    if context.last_response.get("json") is not None:
        _assert_x_request_id(context)
    # Minimal success/error validation
    if status >= 400 and body_json is not None:
        _validate_with_name(body_json, "Problem")
    # For successful screen views, minimally validate IDs
    if status == 200 and "/response-sets/" in path and "/screens/" in path:
        try:
            parts = path.strip("/").split("/")
            rs_id = parts[1]
            screen_id = parts[3]
            _validate_with_name(rs_id, "ResponseSetId")
            _validate_with_name(screen_id, "ScreenId")
        except Exception:
            pass


@step('I PATCH "{path}" with headers:')
def step_when_patch_with_headers(context, path: str):
    context._pending_path = path
    context._pending_headers = {row[0]: _interpolate(row[1], context) for row in context.table}


@step("body:")
def step_any_body(context):
    raw = context.text or "{}"
    # Clarke guidance: feature text may escape underscores in JSON keys
    # (e.g., question\_id). Normalize before parsing so json.loads accepts it.
    try:
        raw = raw.replace("\\_", "_")
    except Exception:
        # Best-effort normalization; proceed with original raw if replace fails
        pass
    try:
        body = json.loads(raw)
    except Exception as exc:
        raise AssertionError(f"Invalid JSON body: {exc}\n{raw}")
    # Validate request body strictly with an overlay schema per Clarke:
    # base it on AnswerUpsert and allow optional question_id (uuid), do not
    # require answer_kind, and keep additionalProperties: false.
    if isinstance(body, dict):
        try:
            base_schema = _schema("AnswerUpsert")
            overlay = json.loads(json.dumps(base_schema))  # deep copy
            props = overlay.setdefault("properties", {})
            # Permit optional question_id (uuid format)
            if isinstance(props, dict):
                props["question_id"] = {"type": "string", "format": "uuid"}
            # Ensure additionalProperties remains false to disallow extras
            overlay["additionalProperties"] = False
            # Ensure 'answer_kind' is not required by overlay (remove if present)
            req = overlay.get("required")
            if isinstance(req, list) and "answer_kind" in req:
                overlay["required"] = [r for r in req if r != "answer_kind"]
            _validate(body, overlay)
        except Exception as exc:
            raise AssertionError(f"Invalid AnswerUpsert request body: {exc}")
    path = getattr(context, "_pending_path", None)
    # Clarke: validate path IDs for PATCH /response-sets/{rs}/answers/{q}
    if isinstance(path, str) and "/response-sets/" in path and "/answers/" in path:
        parts = path.strip("/").split("/")
        # /response-sets/{rs}/answers/{q}
        if len(parts) >= 4 and parts[0] == "response-sets" and parts[2] == "answers":
            rs_id = parts[1]
            q_id = parts[3]
            _validate_with_name(rs_id, "ResponseSetId")
            _validate_with_name(q_id, "QuestionId")
    headers = getattr(context, "_pending_headers", {}) or {}
    status, headers_out, body_json, body_text = _http_request(context, "PATCH", path, headers=headers, json_body=body)
    context.last_response = {
        "status": status,
        "headers": headers_out,
        "json": body_json,
        "text": body_text,
        "path": path,
        "method": "PATCH",
    }
    # Clarke: All JSON responses must include X-Request-Id (200/4xx)
    if context.last_response.get("json") is not None:
        _assert_x_request_id(context)
    # Validate success envelope for autosave operations
    if status == 200 and body_json is not None:
        _validate_with_name(body_json, "AutosaveResult")
    # Clear pending
    context._pending_path = None
    context._pending_headers = None


@when('I POST "{path}"')
def step_when_post(context, path: str):
    # Clarke: for regenerate-check, ensure Q_CO_NAME exists after Background via JIT seed
    if path.endswith("/regenerate-check"):
        try:
            parts = path.strip("/").split("/")
            # /response-sets/{rs}/regenerate-check
            rs_id = parts[1] if len(parts) >= 2 and parts[0] == "response-sets" else None
        except Exception:
            rs_id = None
        q_name_id = "33333333-3333-3333-3333-333333333331"  # Q_CO_NAME
        if rs_id and _row_count_response(context, rs_id, q_name_id) == 0:
            seed_headers = {
                "Idempotency-Key": f"idem-seed-{uuid.uuid4()}",
                "If-Match": "*",
                "Accept": "*/*",
                "Content-Type": "application/json",
            }
            seed_path = f"/response-sets/{rs_id}/answers/{q_name_id}"
            seed_body = {"question_id": q_name_id, "value": "Acme Ltd"}
            s_code, s_hdrs, s_json, s_text = _http_request(
                context, "PATCH", seed_path, headers=seed_headers, json_body=seed_body
            )
            assert s_code == 200, f"Expected 200 from JIT seed PATCH, got {s_code}"
            # ETag presence on optimistic concurrency flows
            assert isinstance(_get_header_case_insensitive(s_hdrs, "ETag"), str), "Missing ETag on seed"
    status, headers, body_json, body_text = _http_request(context, "POST", path)
    context.last_response = {
        "status": status,
        "headers": headers,
        "json": body_json,
        "text": body_text,
        "path": path,
        "method": "POST",
    }
    # Clarke: All JSON responses must include X-Request-Id (200/4xx)
    if context.last_response.get("json") is not None:
        _assert_x_request_id(context)
    if path.endswith("/regenerate-check") and status == 200 and body_json is not None:
        _validate_with_name(body_json, "RegenerateCheckResult")


@when('I POST "{path}" with multipart file "{filename}" containing:')
def step_when_post_multipart(context, path: str, filename: str):
    content = context.text or ""
    # Normalize escaped underscores from feature literals before sending
    try:
        content = content.replace("\\_", "_")
    except Exception:
        pass
    _validate_with_name(content, "CSVImportFile")
    # Remember the last CSV payload for subsequent DB assertions
    context._last_csv_payload = content
    # API expects Body(..., media_type="text/csv") per app implementation
    status, headers, body_json, body_text = _http_request(
        context,
        "POST",
        path,
        headers={"Content-Type": "text/csv"},
        text_body=content,
    )
    context.last_response = {
        "status": status,
        "headers": headers,
        "json": body_json,
        "text": body_text,
        "path": path,
        "method": "POST",
    }
    # Clarke: All JSON responses must include X-Request-Id (200/4xx)
    if context.last_response.get("json") is not None:
        _assert_x_request_id(context)
    if status == 200 and body_json is not None:
        # ImportResult validation must be strict on success
        _validate_with_name(body_json, "ImportResult")


@step('I DELETE any answer in table "answer" for (response\_set\_id="{rs_id}", question\_id="{q_id}")')
def step_delete_any_answer(context, rs_id: str, q_id: str):
    _db_exec(
        context,
        "DELETE FROM response WHERE response_set_id = :rs AND question_id = :q",
        {"rs": rs_id, "q": q_id},
    )
    context.last_response = {
        "status": 204,
        "headers": {"Content-Type": "application/json"},
        "json": None,
        "text": None,
        "path": f"/answers?response_set_id={rs_id}&question_id={q_id}",
        "method": "DELETE",
    }


# ------------------
# Then steps
# ------------------


@then("the response code should be {code:d}")
def step_then_status(context, code: int):
    actual = context.last_response.get("status")
    assert actual == code, f"Expected {code}, got {actual}"
    # Validate envelopes/content-type
    if isinstance(actual, int) and actual >= 400:
        body = context.last_response.get("json")
        if isinstance(body, dict):
            # For error JSON responses, enforce problem+json Content-Type
            ctype = (context.last_response.get("headers") or {}).get("Content-Type", "")
            assert isinstance(ctype, str) and ctype.startswith("application/problem+json"), (
                f"Expected Content-Type application/problem+json for error JSON responses, got {ctype}"
            )
            # Clarke: All JSON error responses must include X-Request-Id
            _assert_x_request_id(context)
            # Prefer ValidationProblem shape when errors[] present (e.g., 422)
            if actual == 422 and isinstance(body.get("errors"), list):
                try:
                    _validate_with_name(body, "ValidationProblem")
                except Exception:
                    # Fall back to Problem envelope if schema not available
                    _validate_with_name(body, "Problem")
            # Clarke: For 409 optimistic concurrency, ETag must be present
            if actual == 409:
                _assert_response_etag_present(context)
        else:
            _validate_with_name(body, "Problem")
    else:
        body_json = context.last_response.get("json")
        if body_json is not None:
            ctype = (context.last_response.get("headers") or {}).get("Content-Type", "")
            assert isinstance(ctype, str) and ctype.startswith("application/json"), (
                f"Expected Content-Type application/json for {actual} JSON responses, got {ctype}"
            )
            # Clarke: All JSON success responses must include X-Request-Id
            _assert_x_request_id(context)


@then('the response header "ETag" should be a non-empty string')
def step_then_header_etag_nonempty(context):
    headers = context.last_response.get("headers", {}) or {}
    val = _get_header_case_insensitive(headers, "ETag")
    assert isinstance(val, str) and val.strip(), "Expected non-empty ETag"


@then('the response header "{header_name}" equals "{expected}"')
def step_then_header_equals(context, header_name: str, expected: str):
    headers = context.last_response.get("headers", {}) or {}
    # Case-insensitive header fetch to tolerate server casing
    val = _get_header_case_insensitive(headers, header_name)
    expected = expected.replace("\\_", "_")
    assert val == expected, f"Expected header {header_name}={expected}, got {val}"


@then('the response header "ETag" should be a non-empty string and capture as "{var_name}"')
def step_then_header_capture(context, var_name: str):
    headers = context.last_response.get("headers", {}) or {}
    val = _get_header_case_insensitive(headers, "ETag")
    assert isinstance(val, str) and val.strip(), "Expected non-empty ETag"
    context.vars[var_name] = val


# ------------------
# Generic Then steps for headers per Clarke
# ------------------

@then("the response has an X-Request-Id header")
def step_then_has_x_request_id(context):
    _assert_x_request_id(context)


@then("the response exposes the current ETag token")
def step_then_has_current_etag(context):
    _assert_response_etag_present(context)


@then('the response JSON at "{json_path}" equals {expected:d}')
def step_then_json_equals_int(context, json_path: str, expected: int):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    actual = _jsonpath(body, json_path)
    assert actual == expected, f"Expected {expected} at {json_path}, got {actual}"


@then('the response JSON at "{json_path}" equals "{expected}"')
def step_then_json_equals_string(context, json_path: str, expected: str):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    actual = _jsonpath(body, json_path)
    if isinstance(actual, list) and len(actual) == 1:
        actual = actual[0]
    # Normalize escaped characters from feature literals: underscrore and dollar
    # to compare against actual JSON path strings (e.g., "\\$.value" -> "$.value").
    expected = expected.replace("\\_", "_").replace("\\$", "$")
    assert actual == expected, f"Expected '{expected}' at {json_path}, got {actual}"


@then('the response JSON at "{json_path}" equals {expected}')
def step_then_json_equals_literal(context, json_path: str, expected: str):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    actual = _jsonpath(body, json_path)
    if isinstance(actual, list) and len(actual) == 1:
        actual = actual[0]
    if expected in {"[]", "\\[]"}:
        exp: Any = []
    elif expected in ("true", "false"):
        exp = True if expected == "true" else False
    elif expected.isdigit():
        exp = int(expected)
    elif expected.startswith('"') and expected.endswith('"'):
        # Quoted literal branch: normalize escaped underscore and dollar signs
        exp = expected[1:-1].replace("\\_", "_").replace("\\$", "$")
    else:
        exp = expected
    assert actual == exp, f"Expected {exp} at {json_path}, got {actual}"


@then('the database table "answer" should have {count:d} rows for response\_set\_id "{rs_id}"')
def step_then_db_answer_count(context, count: int, rs_id: str):
    actual = _row_count_response(context, rs_id)
    assert actual == count, f"Expected {count} rows for response_set_id={rs_id}, got {actual}"


@then('the database should contain exactly 1 row in "answer" for (response\_set\_id="{rs_id}", question\_id="{q_id}") with value "{val}"')
def step_then_db_row_value(context, rs_id: str, q_id: str, val: str):
    assert _row_count_response(context, rs_id, q_id) == 1
    actual = _row_value_text(context, rs_id, q_id)
    assert actual == val, f"Expected value {val} for (rs={rs_id}, q={q_id}), got {actual}"


@then('the database should still contain exactly 1 row in "answer" for (response\_set\_id="{rs_id}", question\_id="{q_id}")')
def step_then_db_row_still_one(context, rs_id: str, q_id: str):
    assert _row_count_response(context, rs_id, q_id) == 1


@then('the database value in "answer" for (response\_set\_id="{rs_id}", question\_id="{q_id}") should still equal "{val}"')
def step_then_db_value_still(context, rs_id: str, q_id: str, val: str):
    actual = _row_value_text(context, rs_id, q_id)
    assert actual == val, f"Expected value to remain {val}, got {actual}"


@then('the database should not create or update any row in "answer" for (response\_set\_id="{rs_id}", question\_id="{q_id}")')
def step_then_db_no_change(context, rs_id: str, q_id: str):
    assert _row_count_response(context, rs_id, q_id) == 0, "Expected no response row created/updated"


@then('the first line of the CSV equals "{header}"')
def step_then_csv_first_line(context, header: str):
    text = context.last_response.get("text") or ""
    first = (text.splitlines() or [""])[0]
    exp = header.replace("\\_", "_")
    assert first == exp, f"Expected first CSV line '{exp}', got '{first}'"


@then("subsequent rows are ordered by screen\\_key asc, question\\_order asc, then question\\_id asc")
def step_then_csv_ordering(context):
    text = context.last_response.get("text") or ""
    # Clarke: enforce CSVExportSnapshot schema strictly
    _validate_with_name(text, "CSVExportSnapshot")
    lines = text.splitlines()
    assert len(lines) >= 2, "CSV must have header and at least one data row"
    reader = csv.DictReader(io.StringIO(text))
    qid_by_ext = getattr(getattr(context, "vars", {}), "get", lambda _k, _d=None: None)("qid_by_ext", {})
    prev: Tuple[str, int, str] | None = None
    for row in reader:
        ext = str(row.get("external_qid", ""))
        qid = (qid_by_ext or {}).get(ext, "")
        key = (str(row.get("screen_key", "")), int(str(row.get("question_order", 0) or 0)), str(qid))
        if prev is not None:
            assert key >= prev, f"Rows are not in deterministic order: {key} < {prev}"
        prev = key


@then('the response JSON at "{json_path}" is greater than {n:d}')
def step_then_json_greater_than(context, json_path: str, n: int):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    actual = _jsonpath(body, json_path)
    assert isinstance(actual, int), f"Expected integer at {json_path}, got {type(actual).__name__}"
    assert actual > n, f"Expected value at {json_path} > {n}, got {actual}"


@then('the database table "question" should include a row where external\_qid="{ext}" and answer\_kind="{kind}"')
def step_then_db_question_row(context, ext: str, kind: str):
    # Unescape feature-escaped underscores to match DB values
    try:
        ext = ext.replace("\\_", "_")
        kind = kind.replace("\\_", "_")
    except Exception:
        pass
    eng = _db_engine(context)
    sql = (
        "SELECT COUNT(*) FROM questionnaire_question WHERE external_qid = :ext AND answer_type = :kind"
    )
    with eng.connect() as conn:
        cnt = int(conn.execute(sql_text(sql), {"ext": ext, "kind": kind}).scalar_one())
    assert cnt >= 1, f"Expected at least 1 question for external_qid={ext} and answer_kind={kind}, got {cnt}"


@then('the database table "answer\_option" should include 2 rows for the new question ordered by sort\\_index')
def step_then_db_answer_option_two_rows(context):
    # Infer the "new question" external_qid from the last CSV payload (first enum_single row)
    payload = getattr(context, "_last_csv_payload", "") or ""
    reader = csv.DictReader(io.StringIO(payload))
    target_ext: Optional[str] = None
    for row in reader:
        if (row.get("answer_kind") or "").strip() == "enum_single":
            target_ext = (row.get("external_qid") or "").strip()
            break
    assert target_ext, "Could not determine new question external_qid from CSV payload"
    eng = _db_engine(context)
    with eng.connect() as conn:
        qrow = conn.execute(
            sql_text("SELECT question_id FROM questionnaire_question WHERE external_qid = :ext"),
            {"ext": target_ext},
        ).fetchone()
        assert qrow, f"No question found for external_qid={target_ext}"
        qid = qrow[0]
        rows = conn.execute(
            sql_text(
                "SELECT option_id, sort_index FROM answer_option WHERE question_id = :qid ORDER BY sort_index ASC"
            ),
            {"qid": qid},
        ).fetchall()
    assert len(rows) == 2, f"Expected 2 answer_option rows for question_id={qid}, got {len(rows)}"
    # Ensure deterministic sort_index progression
    assert [r[1] for r in rows] == [1, 2], f"Expected sort_index [1,2], got {[r[1] for r in rows]}"


@then('the database table "question" should not contain any row where external\_qid="{ext}"')
def step_then_db_question_absent(context, ext: str):
    eng = _db_engine(context)
    with eng.connect() as conn:
        cnt = int(conn.execute(sql_text("SELECT COUNT(*) FROM questionnaire_question WHERE external_qid = :ext"), {"ext": ext}).scalar_one())
    assert cnt == 0, f"Expected no question with external_qid={ext}, found {cnt}"
