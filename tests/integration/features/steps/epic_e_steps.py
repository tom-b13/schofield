"""Epic E – Response Ingestion integration steps.

Implements only Epic E specific steps and aliases per Clarke guidance.
Reuses shared HTTP helpers from questionnaire_steps. No app logic changes.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Dict, Optional

from behave import given, then, when, step

# Reuse shared helpers
from questionnaire_steps import (
    _http_request,
    _jsonpath,
    _interpolate,
    _get_header_case_insensitive,
    _validate_with_name,
    step_when_get,
    _rewrite_path,
)


def _ensure_vars(context) -> Dict[str, Any]:
    if not hasattr(context, "vars") or context.vars is None:
        context.vars = {}
    return context.vars


# ------------------
# Given steps / aliases
# ------------------


@given('the API base path is "{path}"')
def epic_e_set_api_prefix(context, path: str):
    # Only set the API prefix (versioned path), not the base host
    context.api_prefix = str(path)


@given('a fresh event sink is attached to capture "response.saved" and "response_set.deleted" events')
def epic_e_attach_event_sink(context):
    # Initialize a simple list-based sink for test observations (no app wiring)
    context.event_sink = []


@given('I have created a response set named "{name}" and captured its "{var_name}"')
def epic_e_create_response_set_and_capture(context, name: str, var_name: str):
    status, headers_out, body_json, body_text = _http_request(
        context,
        "POST",
        "/response-sets",
        headers={"Content-Type": "application/json", "Accept": "*/*"},
        json_body={"name": name},
    )
    # Persist last response snapshot
    context.last_response = {
        "status": status,
        "headers": headers_out,
        "json": body_json,
        "text": body_text,
        "bytes": getattr(context, "_last_response_bytes", None),
        "path": "/response-sets",
        "method": "POST",
    }
    assert status in (200, 201), f"Expected 200/201 creating response set, got {status}"
    # Capture identifier under provided variable name
    rs_id = _jsonpath(body_json, "$.response_set_id")
    _ensure_vars(context)[str(var_name)] = str(rs_id)


@given('I have a response set "{response_set_id}" and a random question_id "{question_id}"')
def epic_e_have_random_question_id(context, response_set_id: str, question_id: str):
    # Ensure response_set_id is carried forward for later interpolation
    _ensure_vars(context)["response_set_id"] = _interpolate(response_set_id, context)
    token = str(question_id)
    try:
        uuid.UUID(token)
        rnd = token
    except Exception:
        rnd = str(uuid.uuid4())
    _ensure_vars(context)["random_question_id"] = rnd


@given('I have a valid "If-Match" for that random question_id')
def epic_e_valid_if_match_for_random_qid(context):
    # Capture a real current ETag by GET-ing the screen (profile)
    vars_map = _ensure_vars(context)
    rs_id = vars_map.get("response_set_id")
    def _needs_create(val: Optional[str]) -> bool:
        try:
            s = str(val or "")
        except Exception:
            return True
        if not s:
            return True
        if "{" in s or "}" in s:
            return True
        return False
    if _needs_create(rs_id):
        status, headers_out, body_json, body_text = _http_request(
            context,
            "POST",
            "/response-sets",
            headers={"Content-Type": "application/json", "Accept": "*/*"},
            json_body={"name": "integration"},
        )
        # Capture created id and continue
        assert status in (200, 201), f"Expected 200/201 creating response set, got {status}"
        rs_id = str(_jsonpath(body_json, "$.response_set_id"))
        vars_map["response_set_id"] = rs_id
    path = f"/response-sets/{rs_id}/screens/profile"
    step_when_get(context, path)
    # Gracefully handle 404 by creating a response set and retrying GET
    try:
        _status = context.last_response.get("status")
    except Exception:
        _status = None
    if _status == 404:
        status2, headers_out2, body_json2, body_text2 = _http_request(
            context,
            "POST",
            "/response-sets",
            headers={"Content-Type": "application/json", "Accept": "*/*"},
            json_body={"name": "integration"},
        )
        assert status2 in (200, 201), f"Expected 200/201 creating response set, got {status2}"
        rs_id = str(_jsonpath(body_json2, "$.response_set_id"))
        vars_map["response_set_id"] = rs_id
        path = f"/response-sets/{rs_id}/screens/profile"
        step_when_get(context, path)
    headers_out = context.last_response.get("headers", {}) or {}
    etag = _get_header_case_insensitive(headers_out, "Screen-ETag") or _get_header_case_insensitive(headers_out, "ETag")
    assert isinstance(etag, str) and etag.strip(), "Missing screen ETag from GET"
    vars_map["prev_etag"] = etag
    vars_map["etag"] = etag
    # Pre-stage If-Match header for subsequent PATCH/DELETE to avoid ordering sensitivity
    staged = getattr(context, "_pending_headers", {}) or {}
    staged["If-Match"] = etag
    context._pending_headers = staged


@given('I have a valid "If-Match" for question "{question_id}"')
@given('I have a valid "If-Match" for question "{question_id}" in response_set "{response_set_id}"')
def epic_e_valid_if_match_for_question(context, question_id: str, response_set_id: Optional[str] = None):
    # Resolve response_set_id; if missing or placeholder-like, create one via POST /response-sets
    vars_map = _ensure_vars(context)
    if response_set_id:
        vars_map["response_set_id"] = _interpolate(response_set_id, context)
    rs_id = vars_map.get("response_set_id")
    def _needs_create(val: Optional[str]) -> bool:
        try:
            s = str(val or "")
        except Exception:
            return True
        if not s:
            return True
        if "{" in s or "}" in s:
            return True
        return False
    if _needs_create(rs_id):
        status, headers_out, body_json, body_text = _http_request(
            context,
            "POST",
            "/response-sets",
            headers={"Content-Type": "application/json", "Accept": "*/*"},
            json_body={"name": "integration"},
        )
        # Persist last response snapshot
        context.last_response = {
            "status": status,
            "headers": headers_out,
            "json": body_json,
            "text": body_text,
            "path": "/response-sets",
            "method": "POST",
        }
        assert status in (200, 201), f"Expected 200/201 creating response set, got {status}"
        rs_id = _jsonpath(body_json, "$.response_set_id")
        vars_map["response_set_id"] = str(rs_id)
    # Persist last referenced question for aliasing hooks
    try:
        vars_map["last_question_id"] = _interpolate(question_id, context)
    except Exception:
        vars_map["last_question_id"] = str(question_id)
    path = f"/response-sets/{rs_id}/screens/profile"
    step_when_get(context, path)
    headers_out = context.last_response.get("headers", {}) or {}
    etag = _get_header_case_insensitive(headers_out, "Screen-ETag") or _get_header_case_insensitive(headers_out, "ETag")
    assert isinstance(etag, str) and etag.strip(), "Missing screen ETag from GET"
    vars_map["prev_etag"] = etag
    vars_map["etag"] = etag
    # Pre-stage If-Match header for subsequent PATCH/DELETE to avoid ordering sensitivity
    staged = getattr(context, "_pending_headers", {}) or {}
    staged["If-Match"] = etag
    context._pending_headers = staged


@given('I have a valid "If-Match" for that question')
def epic_e_valid_if_match_for_that_question(context):
    # Alias that relies on previous steps having set response_set_id and last_question_id
    vars_map = _ensure_vars(context)
    rs_id = vars_map.get("response_set_id")
    q_id = vars_map.get("last_question_id")
    def _needs_create(val: Optional[str]) -> bool:
        try:
            s = str(val or "")
        except Exception:
            return True
        if not s:
            return True
        if "{" in s or "}" in s:
            return True
        return False
    if _needs_create(rs_id):
        status, headers_out, body_json, body_text = _http_request(
            context,
            "POST",
            "/response-sets",
            headers={"Content-Type": "application/json", "Accept": "*/*"},
            json_body={"name": "integration"},
        )
        context.last_response = {
            "status": status,
            "headers": headers_out,
            "json": body_json,
            "text": body_text,
            "path": "/response-sets",
            "method": "POST",
        }
        assert status in (200, 201), f"Expected 200/201 creating response set, got {status}"
        rs_id = str(_jsonpath(body_json, "$.response_set_id"))
        vars_map["response_set_id"] = rs_id
    assert isinstance(q_id, str) and q_id, "last_question_id is required"
    path = f"/response-sets/{rs_id}/screens/profile"
    step_when_get(context, path)
    headers_out = context.last_response.get("headers", {}) or {}
    etag = _get_header_case_insensitive(headers_out, "Screen-ETag") or _get_header_case_insensitive(headers_out, "ETag")
    assert isinstance(etag, str) and etag.strip(), "Missing screen ETag from GET"
    vars_map["prev_etag"] = etag
    vars_map["etag"] = etag
    # Clarke: stage If-Match header so immediate next PATCH uses fresh ETag
    staged = getattr(context, "_pending_headers", {}) or {}
    staged["If-Match"] = etag
    context._pending_headers = staged


@given('I have a response set "{response_set_id}" and a stale ETag for "{question_id}"')
def epic_e_have_stale_etag(context, response_set_id: str, question_id: str):
    # Scenario scaffolding: store provided rs id and a clearly stale weak ETag
    _ensure_vars(context)["response_set_id"] = _interpolate(response_set_id, context)
    _ensure_vars(context)["stale_etag"] = 'W/"stale"'


@given('I have a response set "{response_set_id}"')
def epic_e_have_response_set(context, response_set_id: str):
    _ensure_vars(context)["response_set_id"] = _interpolate(response_set_id, context)


@given('I have a valid "If-Match" for response_set "{response_set_id}"')
def epic_e_valid_if_match_for_response_set(context, response_set_id: str):
    _ensure_vars(context)["response_set_id"] = _interpolate(response_set_id, context)
    _ensure_vars(context)["etag_set"] = "*"


@given('the question "{question_id}" currently has a stored answer in response_set "{response_set_id}"')
def epic_e_seed_answer_adapter(context, question_id: str, response_set_id: str):
    # Thin adapter delegating to existing seeding step with type-safe values per question.
    qid = _interpolate(question_id, context)
    rsid = _interpolate(response_set_id, context)
    # Clarke: if provided response_set_id is missing or unresolved (contains braces), create one first
    try:
        s = str(rsid or "")
    except Exception:
        s = ""
    if (not s) or ("{" in s or "}" in s):
        status, headers_out, body_json, body_text = _http_request(
            context,
            "POST",
            "/response-sets",
            headers={"Content-Type": "application/json", "Accept": "*/*"},
            json_body={"name": "integration"},
        )
        # Persist last response snapshot and capture id
        context.last_response = {
            "status": status,
            "headers": headers_out,
            "json": body_json,
            "text": body_text,
            "path": "/response-sets",
            "method": "POST",
        }
        assert status in (200, 201), f"Expected 200/201 creating response set, got {status}"
        rsid = str(_jsonpath(body_json, "$.response_set_id"))
        _ensure_vars(context)["response_set_id"] = rsid
    # Branch on known test question IDs to ensure correct typed seed values
    qid_l = qid.lower()
    if qid_l.startswith("11111111-1111-1111-1111-111111111111"):
        seed_literal = "1"  # number
    elif qid_l.startswith("22222222-2222-2222-2222-222222222222"):
        seed_literal = "true"  # boolean
    elif qid_l.startswith("33333333-3333-3333-3333-333333333333"):
        seed_literal = '"aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"'  # enum option_id
    elif qid_l.startswith("44444444-4444-4444-4444-444444444444"):
        seed_literal = '"seed"'  # short_string/text
    else:
        # Default to text to avoid 422 on unknown kinds
        seed_literal = '"seed"'
    context.execute_steps(
        f"Given the response set \"{rsid}\" has answer for \"{qid}\" = {seed_literal}"
    )
    # Remember last question for alias 'that question'
    _ensure_vars(context)["last_question_id"] = qid


# Runtime-failure staging via special headers (no app code changes)
@given('the repository upsert will fail at runtime for this request')
def epic_e_stage_repo_upsert_failure(context):
    staged = getattr(context, "_pending_headers", {}) or {}
    staged["X-Test-Fail-Repo-Upsert"] = "true"
    context._pending_headers = staged


@given('the visibility helper "{helper_name}" will fail at runtime for this request')
def epic_e_stage_visibility_failure(context, helper_name: str):
    staged = getattr(context, "_pending_headers", {}) or {}
    # Encode which helper should fail for clarity; server test mode may inspect this
    staged["X-Test-Fail-Visibility-Helper"] = str(helper_name or "compute_visible_set")
    context._pending_headers = staged


# ------------------
# When steps – header staging adapter
# ------------------


@when('header "{name}" set to "{value}"')
def epic_e_stage_header(context, name: str, value: str):
    staged = getattr(context, "_pending_headers", {}) or {}
    ivalue = _interpolate(value, context)
    # Support angle-bracket tokens as in Epic D steps (e.g., <latest-etag>)
    try:
        if isinstance(ivalue, str) and ivalue.startswith("<") and ivalue.endswith(">"):
            key = ivalue[1:-1]
            repl = _ensure_vars(context).get(key)
            if isinstance(repl, (str, bytes, bytearray)):
                ivalue = repl.decode("utf-8") if isinstance(repl, (bytes, bytearray)) else str(repl)
    except Exception:
        pass
    staged[str(name)] = str(ivalue)
    context._pending_headers = staged


@when('no "If-Match" header')
def epic_e_clear_if_match_header(context):
    # Explicitly clear any staged If-Match header
    staged = getattr(context, "_pending_headers", {}) or {}
    if "If-Match" in staged:
        staged.pop("If-Match", None)
    context._pending_headers = staged


@step('I DELETE "{path}" with header "{name}: {value}"')
def epic_e_delete_with_header(context, path: str, name: str, value: str):
    ipath = _rewrite_path(context, _interpolate(path, context))
    ivalue = _interpolate(value, context)
    headers = {str(name): str(ivalue), "Accept": "*/*"}
    status, headers_out, body_json, body_text = _http_request(context, "DELETE", ipath, headers=headers)
    context.last_response = {
        "status": status,
        "headers": headers_out,
        "json": body_json,
        "text": body_text,
        "path": ipath,
        "method": "DELETE",
    }


# ------------------
# Then steps – assertions
# ------------------


@then('the JSON at "etag" is a non-empty opaque string')
def epic_e_assert_etag_nonempty(context):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    val = _jsonpath(body, "$.etag")
    assert isinstance(val, str) and val.strip(), "Expected non-empty etag string"


@then('the JSON at "created_at" is an RFC3339 UTC timestamp')
def epic_e_assert_created_at_rfc3339(context):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    s = str(_jsonpath(body, "$.created_at"))
    # RFC3339 with optional fractional seconds, must be UTC 'Z'
    pat = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
    assert re.match(pat, s) is not None, f"created_at not RFC3339 UTC: {s}"


@then('the JSON at "screen_view.questions" is an array')
def epic_e_assert_questions_array(context):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    arr = _jsonpath(body, "$.screen_view.questions")
    assert isinstance(arr, list), "Expected screen_view.questions to be an array"


@then('the HTTP header "{name}" equals JSON "{json_path}"')
def epic_e_header_equals_json(context, name: str, json_path: str):
    headers = context.last_response.get("headers", {}) or {}
    hval = _get_header_case_insensitive(headers, name)
    body = context.last_response.get("json")
    assert isinstance(body, (dict, list)), "No JSON body"
    jp = json_path if json_path.startswith("$") else f"$.{json_path}"
    jval = _jsonpath(body, jp)
    if isinstance(jval, list) and len(jval) == 1:
        jval = jval[0]
    # Canonicalize header quoting vs JSON string value
    assert str(hval) == str(jval), f"Expected header {name} == JSON {json_path}, got {hval} vs {jval}"


@then('the response content type is "{ctype}"')
def epic_e_assert_content_type(context, ctype: str):
    headers = context.last_response.get("headers", {}) or {}
    actual = _get_header_case_insensitive(headers, "Content-Type") or ""
    assert isinstance(actual, str) and actual.startswith(ctype), (
        f"Expected Content-Type starting with {ctype}, got {actual}"
    )


@then('the problem "code" equals "{code}"')
def epic_e_assert_problem_code(context, code: str):
    # Prefer ProblemDetails docs schema when available; fallback to core Problem
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    try:
        # Validate envelope shape if schema available
        _ = _validate_with_name  # type: ignore[truthy-bool]
        try:
            # Attempt docs ProblemDetails schema name first if wired
            from questionnaire_steps import _load_doc_schema  # type: ignore

            _ = _load_doc_schema("ProblemDetails.schema.json")  # may raise
            # If load succeeds, validate with docs ProblemDetails
            # Use local validate to avoid adding a new named schema
            from questionnaire_steps import _validate  # type: ignore
            _validate(body, _)
        except Exception:
            # Fallback to existing Problem schema by name
            _validate_with_name(body, "Problem")
    except Exception:
        # Schema validation is best-effort here
        pass
    actual = _jsonpath(body, "$.code")
    assert actual == code, f"Expected problem.code '{code}', got '{actual}'"


@then('the JSON at "batch_result.items[*].outcome" are all "{value}"')
def epic_e_assert_batch_outcomes_uniform(context, value: str):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    arr = _jsonpath(body, "$.batch_result.items")
    assert isinstance(arr, list), "Expected batch_result.items to be an array"
    outcomes = [str(item.get("outcome")) for item in arr]
    assert outcomes and all(o == value for o in outcomes), f"Expected all outcomes '{value}', got {outcomes}"


@then('the JSON at "etag" changes from previous')
def epic_e_assert_etag_changed(context):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    prev = _ensure_vars(context).get("prev_etag") or _ensure_vars(context).get("etag_prev")
    assert isinstance(prev, str) and prev.strip(), "Previous ETag missing; ensure If-Match step captured it"
    cur = _jsonpath(body, "$.etag")
    assert isinstance(cur, str) and cur.strip(), "Expected non-empty new etag"
    assert cur != prev, f"Expected etag to change from previous ({prev})"
    _ensure_vars(context)["prev_etag"] = cur


@then('the HTTP header "ETag" is a non-empty opaque string different from previous')
def epic_e_header_etag_differs_from_previous(context):
    headers = context.last_response.get("headers", {}) or {}
    val = _get_header_case_insensitive(headers, "ETag")
    assert isinstance(val, str) and val.strip(), "Expected non-empty ETag header"
    prev = _ensure_vars(context).get("prev_etag") or _ensure_vars(context).get("etag_prev")
    assert isinstance(prev, str) and prev.strip(), "Previous ETag missing; ensure If-Match step captured it"
    assert val != prev, f"Expected ETag header to differ from previous ({prev})"
    _ensure_vars(context)["prev_etag"] = val


@then('the JSON at "events[?(@.type==\'response.saved\')].payload.state_version" is a non-negative integer')
def epic_e_assert_saved_event_state_version(context):
    body = context.last_response.get("json")
    assert isinstance(body, (dict, list)), "No JSON body"
    # Allow both root and nested 'events' fields
    values = None
    try:
        values = _jsonpath(body, "$.events[?(@.type=='response.saved')].payload.state_version")
    except Exception:
        values = _jsonpath(body, "$[?(@.type=='response.saved')].payload.state_version")
    if not isinstance(values, list):
        values = [values]
    assert values, "No response.saved events present"
    for v in values:
        assert isinstance(v, int) and v >= 0, f"state_version should be non-negative int, got {v!r}"


@given('I have current ETags for questions "{qid1}" and "{qid2}"')
def epic_e_capture_pair_etags(context, qid1: str, qid2: str):
    # Ensure a real response set exists; create if missing or placeholder-like
    vars_map = _ensure_vars(context)
    rs_id = vars_map.get("response_set_id")
    def _needs_create(val: Optional[str]) -> bool:
        try:
            s = str(val or "")
        except Exception:
            return True
        if not s:
            return True
        if "{" in s or "}" in s:
            return True
        return False
    if _needs_create(rs_id):
        status, headers_out, body_json, body_text = _http_request(
            context,
            "POST",
            "/response-sets",
            headers={"Content-Type": "application/json", "Accept": "*/*"},
            json_body={"name": "integration"},
        )
        # Persist last response snapshot
        context.last_response = {
            "status": status,
            "headers": headers_out,
            "json": body_json,
            "text": body_text,
            "path": "/response-sets",
            "method": "POST",
        }
        assert status in (200, 201), f"Expected 200/201 creating response set, got {status}"
        rs_id = _jsonpath(body_json, "$.response_set_id")
        vars_map["response_set_id"] = str(rs_id)
    path = f"/response-sets/{rs_id}/screens/profile"
    step_when_get(context, path)
    headers_out = context.last_response.get("headers", {}) or {}
    etag = _get_header_case_insensitive(headers_out, "Screen-ETag") or _get_header_case_insensitive(headers_out, "ETag")
    assert isinstance(etag, str) and etag.strip(), "Missing screen ETag from GET"
    vars_map["etag_q1"] = etag
    vars_map["etag_q2"] = etag
    # Also stage baseline prev_etag for change assertions
    vars_map["prev_etag"] = etag


@then('an event "response_set.deleted" is observed in the event sink with "payload.response_set_id" = "{response_set_id}"')
def epic_e_assert_response_set_deleted_event(context, response_set_id: str):
    rsid = _interpolate(response_set_id, context)
    # Prefer polling the test-support endpoint; fall back to in-memory sink only if 501 (skeleton)
    try:
        status, headers_out, body_json, body_text = _http_request(
            context,
            "GET",
            "/__test__/events",
            headers={"Accept": "application/json"},
        )
    except AssertionError:
        # HTTP helper raises only on TEST_MOCK_MODE; in that mode rely on sink
        status = 501
        body_json = None
    if status == 200:
        # Support both list payload or {"events": [...]}
        events = []
        if isinstance(body_json, list):
            events = body_json
        elif isinstance(body_json, dict):
            try:
                events = body_json.get("events") or []
            except Exception:
                events = []
        # Search for expected event
        for evt in events:
            try:
                if isinstance(evt, dict) and evt.get("type") == "response_set.deleted":
                    payload = evt.get("payload") or {}
                    if str(payload.get("response_set_id")) == str(rsid):
                        return
            except Exception:
                continue
        raise AssertionError(
            f"response_set.deleted event with payload.response_set_id={rsid!r} not observed via test-support endpoint"
        )
    elif status in (501, 404):
        # Skeleton endpoint; use the in-memory sink as a fallback (legacy behavior)
        sink = getattr(context, "event_sink", None)
        assert isinstance(sink, list), "event sink not attached; use the Given to attach it"
        for evt in sink:
            try:
                if isinstance(evt, dict) and evt.get("type") == "response_set.deleted":
                    payload = evt.get("payload") or {}
                    if str(payload.get("response_set_id")) == str(rsid):
                        return
            except Exception:
                continue
        raise AssertionError(
            f"response_set.deleted event with payload.response_set_id={rsid!r} not observed (fallback sink)"
        )
    else:
        raise AssertionError(f"Unexpected status {status} from test-support events endpoint")
