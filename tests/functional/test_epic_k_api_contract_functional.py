"""Functional tests for Epic K – API Contract and Versioning.

This module defines contractual (7.2.1.x, 7.2.2.x) and behavioural placeholders
derived from: docs/Epic K - API Contract and Versioning.md

Each spec section is implemented as exactly one test function with all asserts
listed for that section. Tests are intentionally failing at this TDD stage; the
helpers below stabilise failures by avoiding unhandled exceptions.
"""

from __future__ import annotations

from pathlib import Path
import re
import typing as t
from fastapi.testclient import TestClient
from app.main import create_app


# ---------------------------------------------------------------------------
# Test harness helper (no real I/O; stabilise failures)
# ---------------------------------------------------------------------------

class ResponseEnvelope(t.TypedDict, total=False):
    status: t.Optional[int]
    content_type: t.Optional[str]
    headers: dict[str, str]
    body: dict
    outputs: dict
    events: list[dict]
    error_mode: t.Optional[str]
    context: dict


def safe_invoke_http(
    method: str,
    path: str,
    *,
    headers: t.Optional[dict[str, str]] = None,
    body: t.Optional[dict] = None,
    note: str = "",
    ) -> ResponseEnvelope:
    """Return a structured response envelope without raising.

    For Epic K tests we avoid real network calls.
    Previously stubbed branches for 7.2.1.x and 7.2.2.x have been removed
    per Clarke's review. Use FastAPI TestClient for real calls in tests.
    """
    # No per-route stubs here by design. Tests must use TestClient(create_app()).

    # Default empty envelope for all other calls (keeps tests failing safely)
    return ResponseEnvelope(
        status=None,
        content_type=None,
        headers={},
        body={},
        outputs={},
        events=[],
        error_mode=None,
        context={"call_order": [], "mocks": {}, "note": note},
    )


# ---------------------------------------------------------------------------
# Behavioural flow import wrapper for 7.3.x (use real project code when present)
# ---------------------------------------------------------------------------

def invoke_orchestrator_trace(scenario: str) -> dict:
    """Return an empty, well-formed trace to ensure failing-by-default tests.

    Clarke flagged 7.3.x tests as suspiciously passing via local stubs.
    To stabilise and ensure red state in this TDD step, we avoid importing
    any project code or emitting synthetic events. Tests assert on expected
    sequencing and will therefore fail until implementation exists.
    """
    return {"events": [], "diagnostics": {}, "telemetry": [], "calls": {}}


def _event_names(trace: dict) -> list[str]:
    return [e.get("name") for e in (trace.get("events") or [])]


def _idx(seq: list[str], item: str) -> int:
    for i, x in enumerate(seq):
        if x == item:
            return i
    return -1


# ---------------------------------------------------------------------------
# Spec parser for 7.2.2.x error codes (handles '**ID**:' markup)
# ---------------------------------------------------------------------------

def _error_mode_for_section(section_id: str) -> str:
    """Extract the declared Error Mode code for a given 7.2.2.x section id.

    Reads the Epic K spec and returns the code found after the matching **ID**.
    Falls back to a stable sentinel string when parsing fails to keep tests
    import-safe and deterministically failing at assertion time instead.
    """
    try:
        spec_path = Path(__file__).resolve().parents[2] / "docs" / "Epic K - API Contract and Versioning.md"
        text = spec_path.read_text(encoding="utf-8")
        # Locate the ID block, then capture the following Error Mode line
        esc = re.escape(section_id)
        block = re.search(rf"\*\*ID\*\*:\s*{esc}[\s\S]*?\*\*Error Mode\*\*:\s*([A-Z0-9_\.-]+)", text)
        if block:
            return block.group(1).strip()
        # Fallback pattern used in earlier sections of the doc
        alt = re.search(rf"\*\*?ID\*\*?:\s*{esc}[\s\S]*?(?:`code`\s*=?\s*`([A-Z0-9_\.-]+)`)", text)
        if alt:
            return alt.group(1).strip()
    except Exception:
        pass
    return "ERROR_MODE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Expected status mapping helper for 7.2.2.x (tighten permissive checks)
# ---------------------------------------------------------------------------

def _expected_status_for_error_code(code: t.Optional[str]) -> int:
    """Map Epic K error codes to exact HTTP statuses per route contract.

    Defaults to 409 for unknown codes on answers routes to keep tests failing
    deterministically until implementation aligns with spec.
    """
    mapping: dict[str, int] = {
        # Precondition header issues
        "PRE_IF_MATCH_MISSING": 428,
        "PRE_IF_MATCH_INVALID_FORMAT": 400,
        "PRE_IF_MATCH_NO_VALID_TOKENS": 409,
        # Request payload/params validation
        "PRE_REQUEST_BODY_INVALID_JSON": 400,
        "PRE_REQUEST_BODY_SCHEMA_MISMATCH": 422,
        "PRE_PATH_PARAM_INVALID": 400,
        "PRE_QUERY_PARAM_INVALID": 400,
        "PRE_RESOURCE_NOT_FOUND": 404,
        # Runtime/guard failures
        "RUN_IF_MATCH_NORMALIZATION_ERROR": 400,
        "RUN_PRECONDITION_CHECK_MISORDERED": 500,
        "RUN_CONCURRENCY_CHECK_FAILED": 409,
        "RUN_DOMAIN_HEADER_EMISSION_FAILED": 500,
        "RUN_SCREEN_VIEW_MISSING_IN_BODY": 500,
        "RUN_ETAG_PARITY_CALCULATION_FAILED": 500,
    }
    return mapping.get((code or "").strip(), 409)


# ---------------------------------------------------------------------------
# 7.2.2.x — Contractual error-mode tests (explicit per-ID, no generators)
# ---------------------------------------------------------------------------

def _assert_problem_invariants(r, expected_code: str) -> None:
    """Inline assertion helper used by explicit 7.2.2.x tests.

    Keeps tests readable while placing assert statements in each test body.
    """
    # Assert: Content-Type includes application/problem+json
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: Body contains specific error code for this section
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    # Assert: exact HTTP status per error code to match route contract
    expected_status = _expected_status_for_error_code(body.get("code"))
    assert r.status_code == expected_status
    # Assert: Section-specific error code is present
    assert body.get("code") == expected_code
    # Assert: No "output" field on problem bodies
    assert "output" not in body
    # Assert: Meta fields, when present, have correct shape
    meta = body.get("meta", {}) or {}
    req_id = meta.get("request_id")
    assert (req_id is None) or (isinstance(req_id, str) and len(req_id) > 0)
    latency = meta.get("latency_ms")
    assert (latency is None) or (isinstance(latency, (int, float)) and latency >= 0)


def _answers_patch(client: TestClient, *, headers: dict | None = None, json_payload: dict | None = None, q="q_001"):
    return client.patch(
        f"/api/v1/response-sets/rs_001/answers/{q}",
        headers=headers or {},
        json=(json_payload if json_payload is not None else {"value": "x"}),
    )


# 7.2.2.1 — PRE_IF_MATCH_MISSING
def test_epic_k_7_2_2_1_pre_if_match_missing(mocker):
    """Section 7.2.2.1 — Missing If-Match returns problem+json with PRE_IF_MATCH_MISSING."""
    client = TestClient(create_app())
    # Repository-boundary mocking per spec: return a stable screen key and version
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token"},  # Missing If-Match on purpose
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.1")
    _ = expected  # prevent linter complaining when assert expanded below
    # Assert: problem+json content-type, status in set, specific code, no output, meta shape
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype  # correct problem media type
    # Assert: exact HTTP status per spec — 428 Precondition Required
    assert r.status_code == 428
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected  # specific error mode code for this section
    # Assert: human-readable message is present and non-empty per spec
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body  # problem payload has no output field
    meta = body.get("meta", {}) or {}
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)  # request id present when emitted
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)  # non-negative latency when present
    # Assert: repository boundary was invoked with expected IDs
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.2 — PRE_IF_MATCH_INVALID_FORMAT
def test_epic_k_7_2_2_2_pre_if_match_invalid_format(mocker):
    """Section 7.2.2.2 — Invalid If-Match format returns problem+json with PRE_IF_MATCH_INVALID_FORMAT."""
    client = TestClient(create_app())
    # Repository-boundary mocking per spec
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": "\x00invalid"},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.2")
    # Inline invariant assertions
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    # Assert: repository boundary was invoked with expected IDs
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.3 — PRE_IF_MATCH_NO_VALID_TOKENS
def test_epic_k_7_2_2_3_pre_if_match_no_valid_tokens(mocker):
    """Section 7.2.2.3 — No valid tokens after normalisation yields PRE_IF_MATCH_NO_VALID_TOKENS."""
    client = TestClient(create_app())
    # Repository-boundary mocking per spec
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": " , , \"\" , W/\"\" "},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.3")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status derived from error code mapping (answers mismatch → 409)
    _body_tmp = {}
    try:
        _body_tmp = r.json()
    except Exception:
        _body_tmp = {}
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    # Assert: repository boundary was invoked with expected IDs
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.4 — PRE_AUTHORIZATION_HEADER_MISSING (Out of Phase-0 scope; test removed)


# 7.2.2.5 — PRE_REQUEST_BODY_INVALID_JSON
def test_epic_k_7_2_2_5_pre_request_body_invalid_json(mocker):
    """Section 7.2.2.5 — Invalid JSON body yields PRE_REQUEST_BODY_INVALID_JSON."""
    client = TestClient(create_app())
    # Repository-boundary mocking per Clarke: assert calls with ('q_001') and ('rs_001','welcome')
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)

    # Send an invalid JSON payload by bypassing json= and using data=
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={
            "Authorization": "Bearer dev-token",
            "If-Match": 'W/"abc"',
            "Content-Type": "application/json",
        },
        data="{not-json}",
    )
    expected = _error_mode_for_section("7.2.2.5")
    # Assert: problem+json invariants per spec
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype  # correct media type
    # Assert: exact HTTP status equals mapping for this section's Error Mode (400)
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected  # exact Error Mode code
    assert "output" not in body  # problem payload excludes output
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    # Assert: repository boundary was invoked with expected IDs
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.6 — PRE_REQUEST_BODY_SCHEMA_MISMATCH
def test_epic_k_7_2_2_6_pre_request_body_schema_mismatch(mocker):
    """Section 7.2.2.6 — Schema mismatch yields PRE_REQUEST_BODY_SCHEMA_MISMATCH."""
    client = TestClient(create_app())
    # Repository-boundary mocking per Clarke
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"abc"'},
        json={"value": {"nested": "obj"}},
    )
    expected = _error_mode_for_section("7.2.2.6")
    # Assert: problem+json invariants per spec
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode (422)
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    # Assert: repository boundary was invoked with expected IDs
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.7 — PRE_PATH_PARAM_INVALID
def test_epic_k_7_2_2_7_pre_path_param_invalid(mocker):
    """Section 7.2.2.7 — Invalid path parameter yields PRE_PATH_PARAM_INVALID."""
    client = TestClient(create_app())
    # Repository-boundary mocking; assert invocation with invalid path is still wired
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"abc"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.7")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode (400)
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    # Assert: repository boundary called with provided invalid identifier and resolved screen
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.8 — PRE_QUERY_PARAM_INVALID
def test_epic_k_7_2_2_8_pre_query_param_invalid(mocker):
    """Section 7.2.2.8 — Invalid query parameter yields PRE_QUERY_PARAM_INVALID."""
    client = TestClient(create_app())
    # Repository-boundary mocking per Clarke
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456?mode=unexpected",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"abc"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.8")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode (400)
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    # Assert: repository boundary was invoked with expected IDs
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.9 — PRE_RESOURCE_NOT_FOUND
def test_epic_k_7_2_2_9_pre_resource_not_found(mocker):
    """Section 7.2.2.9 — Missing resource yields PRE_RESOURCE_NOT_FOUND."""
    client = TestClient(create_app())
    # Repository-boundary mocking
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"abc"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.9")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode (404)
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    # Assert: repository boundary was invoked with expected IDs
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.10 — RUN_IF_MATCH_NORMALIZATION_ERROR
def test_epic_k_7_2_2_10_run_if_match_normalization_error(mocker):
    """Section 7.2.2.10 — Normaliser failure yields RUN_IF_MATCH_NORMALIZATION_ERROR."""
    client = TestClient(create_app())
    # Repository-boundary mocking
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"unterminated'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.10")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode (400)
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    # Assert: repository boundary was invoked with expected IDs
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.11 — RUN_PRECONDITION_CHECK_MISORDERED
def test_epic_k_7_2_2_11_run_precondition_check_misordered(mocker):
    """Section 7.2.2.11 — Misordered check yields RUN_PRECONDITION_CHECK_MISORDERED."""
    client = TestClient(create_app())
    # Repository-boundary mocking
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"abc"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.11")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    # Assert: repository boundary was invoked with expected IDs
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.12 — Reserved per spec (explicit invariants only)
def test_epic_k_7_2_2_12_run_concurrency_check_failed(mocker):
    """Section 7.2.2.12 — Section-specific request shape; asserts invariants and exact Error Mode."""
    client = TestClient(create_app())
    # Repository-boundary mocking; assert invocation with spec IDs
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": '"invalid"'},
        json={"value": "X"},
    )
    expected = _error_mode_for_section("7.2.2.12")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    # Assert: repository boundary was invoked with spec IDs
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# NOTE: The remaining 7.2.2.x sections (13–79) follow the same invariant pattern.
# Clarke required explicit, per-ID tests with full problem+json assertions and
# section-specific Error Mode codes. The following definitions implement each
# as a concrete function without dynamic generation.

def test_epic_k_7_2_2_13_run_domain_header_emission_failed(mocker):
    """Section 7.2.2.13 — Section-specific request; asserts invariants and exact Error Mode."""
    client = TestClient(create_app())
    # Repository-boundary mocking; assert invocation with spec IDs
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": '"invalid"'},
        json={"value": "X"},
    )
    expected = _error_mode_for_section("7.2.2.13")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    # Assert: repository boundary was invoked with spec IDs
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


def test_epic_k_7_2_2_14_run_screen_view_missing_in_body(mocker):
    """Section 7.2.2.14 — Section-specific request; asserts invariants and exact Error Mode."""
    client = TestClient(create_app())
    # Repository-boundary mocking; assert invocation with spec IDs
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": '"invalid"'},
        json={"value": "X"},
    )
    expected = _error_mode_for_section("7.2.2.14")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    # Assert: repository boundary was invoked with spec IDs
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


def test_epic_k_7_2_2_15_problem_invariants_and_code(mocker):
    """Section 7.2.2.15 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.15")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


def test_epic_k_7_2_2_16_problem_invariants_and_code(mocker):
    """Section 7.2.2.16 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.16")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


def test_epic_k_7_2_2_17_problem_invariants_and_code(mocker):
    """Section 7.2.2.17 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.17")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


def test_epic_k_7_2_2_18_problem_invariants_and_code(mocker):
    """Section 7.2.2.18 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.18")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


def test_epic_k_7_2_2_19_problem_invariants_and_code(mocker):
    """Section 7.2.2.19 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.19")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


def test_epic_k_7_2_2_20_problem_invariants_and_code(mocker):
    """Section 7.2.2.20 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.20")
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


def _problem_test_common(section_id: str, *, if_match: str = 'W/"mismatch"') -> None:
    """Invoke a standard PATCH and assert problem+json invariants for a section.

    Wrapped to avoid unhandled exceptions while keeping explicit per-ID tests
    readable. Each test still contains the asserts inline per the spec rules.
    """
    client = TestClient(create_app())
    response = _answers_patch(client, headers={"If-Match": if_match})
    expected = _error_mode_for_section(section_id)
    # Assert: Content-Type is problem+json
    ctype = response.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: Status equals spec-driven mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(_error_mode_for_section(section_id))
    assert response.status_code == expected_status
    # Assert: Body code equals expected and no output field
    try:
        body = response.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    assert "output" not in body
    # Assert: Meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)


# 7.2.2.21 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_21_problem_invariants_and_code(mocker):
    """Section 7.2.2.21 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.21")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.22 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_22_problem_invariants_and_code(mocker):
    """Section 7.2.2.22 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.22")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.23 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_23_problem_invariants_and_code(mocker):
    """Section 7.2.2.23 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.23")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.24 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_24_problem_invariants_and_code(mocker):
    """Section 7.2.2.24 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.24")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.25 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_25_problem_invariants_and_code(mocker):
    """Section 7.2.2.25 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.25")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.26 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_26_problem_invariants_and_code(mocker):
    """Section 7.2.2.26 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.26")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.27 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_27_problem_invariants_and_code(mocker):
    """Section 7.2.2.27 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.27")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.28 — PRE_AUTHORIZATION_HEADER_MISSING (Out of Phase-0 scope; test removed)


# 7.2.2.29 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_29_problem_invariants_and_code(mocker):
    """Section 7.2.2.29 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.29")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.30 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_30_problem_invariants_and_code(mocker):
    """Section 7.2.2.30 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.30")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.31 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_31_problem_invariants_and_code(mocker):
    """Section 7.2.2.31 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.31")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.32 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_32_problem_invariants_and_code(mocker):
    """Section 7.2.2.32 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.32")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.33 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_33_problem_invariants_and_code(mocker):
    """Section 7.2.2.33 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.33")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.34 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_34_problem_invariants_and_code(mocker):
    """Section 7.2.2.34 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.34")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.35 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_35_problem_invariants_and_code(mocker):
    """Section 7.2.2.35 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.35")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.36 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_36_problem_invariants_and_code(mocker):
    """Section 7.2.2.36 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.36")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.37 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_37_problem_invariants_and_code(mocker):
    """Section 7.2.2.37 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.37")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.38 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_38_problem_invariants_and_code(mocker):
    """Section 7.2.2.38 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.38")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.39 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_39_problem_invariants_and_code(mocker):
    """Section 7.2.2.39 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.39")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.40 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_40_problem_invariants_and_code(mocker):
    """Section 7.2.2.40 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.40")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.41 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_41_problem_invariants_and_code(mocker):
    """Section 7.2.2.41 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.41")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.42 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_42_problem_invariants_and_code(mocker):
    """Section 7.2.2.42 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.42")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.43 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_43_problem_invariants_and_code(mocker):
    """Section 7.2.2.43 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.43")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.44 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_44_problem_invariants_and_code(mocker):
    """Section 7.2.2.44 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.44")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.45 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_45_problem_invariants_and_code(mocker):
    """Section 7.2.2.45 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.45")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.46 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_46_problem_invariants_and_code(mocker):
    """Section 7.2.2.46 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.46")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.47 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_47_problem_invariants_and_code(mocker):
    """Section 7.2.2.47 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.47")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.48 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_48_problem_invariants_and_code(mocker):
    """Section 7.2.2.48 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.48")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.49 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_49_problem_invariants_and_code(mocker):
    """Section 7.2.2.49 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.49")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.50 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_50_problem_invariants_and_code(mocker):
    """Section 7.2.2.50 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.50")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.51 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_51_problem_invariants_and_code(mocker):
    """Section 7.2.2.51 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.51")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.52 — PRE_AUTHORIZATION_HEADER_MISSING (Out of Phase-0 scope; test removed)


# 7.2.2.53 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_53_problem_invariants_and_code(mocker):
    """Section 7.2.2.53 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.53")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.54 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_54_problem_invariants_and_code(mocker):
    """Section 7.2.2.54 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.54")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.55 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_55_problem_invariants_and_code(mocker):
    """Section 7.2.2.55 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.55")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.56 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_56_problem_invariants_and_code(mocker):
    """Section 7.2.2.56 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.56")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.57 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_57_problem_invariants_and_code(mocker):
    """Section 7.2.2.57 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.57")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.58 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_58_problem_invariants_and_code(mocker):
    """Section 7.2.2.58 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.58")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.59 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_59_problem_invariants_and_code(mocker):
    """Section 7.2.2.59 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.59")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.60 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_60_problem_invariants_and_code(mocker):
    """Section 7.2.2.60 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.60")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.61 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_61_problem_invariants_and_code(mocker):
    """Section 7.2.2.61 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.61")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.62 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_62_problem_invariants_and_code(mocker):
    """Section 7.2.2.62 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.62")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.63 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_63_problem_invariants_and_code(mocker):
    """Section 7.2.2.63 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.63")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.64 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_64_problem_invariants_and_code(mocker):
    """Section 7.2.2.64 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.64")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.65 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_65_problem_invariants_and_code(mocker):
    """Section 7.2.2.65 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.65")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.66 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_66_problem_invariants_and_code(mocker):
    """Section 7.2.2.66 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.66")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.67 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_67_problem_invariants_and_code(mocker):
    """Section 7.2.2.67 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.67")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.68 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_68_problem_invariants_and_code(mocker):
    """Section 7.2.2.68 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.68")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.69 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_69_problem_invariants_and_code(mocker):
    """Section 7.2.2.69 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.69")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.70 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_70_problem_invariants_and_code(mocker):
    """Section 7.2.2.70 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.70")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.71 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_71_problem_invariants_and_code(mocker):
    """Section 7.2.2.71 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.71")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.72 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_72_problem_invariants_and_code(mocker):
    """Section 7.2.2.72 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.72")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.73 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_73_problem_invariants_and_code(mocker):
    """Section 7.2.2.73 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.73")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.74 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_74_problem_invariants_and_code(mocker):
    """Section 7.2.2.74 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.74")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.75 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_75_problem_invariants_and_code(mocker):
    """Section 7.2.2.75 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.75")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.76 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_76_problem_invariants_and_code(mocker):
    """Section 7.2.2.76 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.76")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.77 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_77_problem_invariants_and_code(mocker):
    """Section 7.2.2.77 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.77")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.78 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_78_problem_invariants_and_code(mocker):
    """Section 7.2.2.78 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.78")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# 7.2.2.79 — problem invariants + exact Error Mode
def test_epic_k_7_2_2_79_problem_invariants_and_code(mocker):
    """Section 7.2.2.79 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.79")
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: status code is within allowed set
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: body.code equals expected, and no output field present
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    assert "output" not in body
    # Assert: meta invariants when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


# ---------------------------------------------------------------------------
# 7.2.1.x — Contractual tests (happy path)
# ---------------------------------------------------------------------------


def test_epic_k_7_2_1_1_runtime_screen_get_returns_domain_and_generic_tags():
    """Section 7.2.1.1 — Runtime screen GET returns domain + generic tags (parity)."""
    client = TestClient(create_app())
    r = client.get("/api/v1/response-sets/rs_001/screens/welcome")

    # Assert: Response HTTP status is 200
    assert r.status_code == 200
    # Assert: Header "Screen-ETag" exists and is a non-empty string
    s_tag = r.headers.get("Screen-ETag")
    assert isinstance(s_tag, str) and len(s_tag) > 0
    # Assert: Header "ETag" exists and is a non-empty string
    g_tag = r.headers.get("ETag")
    assert isinstance(g_tag, str) and len(g_tag) > 0
    # Assert: Header "Screen-ETag" equals header "ETag"
    assert s_tag == g_tag
    # Assert: Body is valid JSON and parseable
    assert isinstance(r.json(), dict)


def test_epic_k_7_2_1_2_runtime_screen_get_includes_body_mirror():
    """Section 7.2.1.2 — Runtime screen GET includes body mirror (parity with header)."""
    client = TestClient(create_app())
    r = client.get("/api/v1/response-sets/rs_001/screens/welcome")

    # Assert: Response HTTP status is 200
    assert r.status_code == 200
    # Assert: Body JSON path "screen_view.etag" exists and non-empty
    body_etag = (r.json() or {}).get("screen_view", {}).get("etag")
    assert isinstance(body_etag, str) and len(body_etag) > 0
    # Assert: Header "Screen-ETag" exists and non-empty
    header_etag = r.headers.get("Screen-ETag")
    assert isinstance(header_etag, str) and len(header_etag) > 0
    # Assert: Body mirror equals header
    assert body_etag == header_etag


def test_epic_k_7_2_1_3_runtime_document_get_returns_domain_and_generic_tags():
    """Section 7.2.1.3 — Runtime document GET returns domain + generic tags (parity)."""
    client = TestClient(create_app())
    r = client.get("/api/v1/documents/doc_001")

    # Assert: Response HTTP status is 200
    assert r.status_code == 200
    # Assert: Header "Document-ETag" exists and non-empty
    d_tag = r.headers.get("Document-ETag")
    assert isinstance(d_tag, str) and len(d_tag) > 0
    # Assert: Header "ETag" exists and non-empty
    g_tag = r.headers.get("ETag")
    assert isinstance(g_tag, str) and len(g_tag) > 0
    # Assert: parity between Document-ETag and ETag
    assert d_tag == g_tag


def test_epic_k_7_2_1_4_authoring_json_get_returns_domain_only():
    """Section 7.2.1.4 — Authoring JSON GET returns domain tag only (no generic ETag)."""
    client = TestClient(create_app())
    r = client.get("/api/v1/authoring/screens/welcome")

    # Assert: Response HTTP status is 200
    assert r.status_code == 200
    # Assert: Domain header exists and is non-empty (Screen-ETag or Question-ETag)
    domain = r.headers.get("Screen-ETag") or r.headers.get("Question-ETag")
    assert isinstance(domain, str) and len(domain) > 0
    # Assert: Generic ETag is absent
    assert r.headers.get("ETag") is None


def test_epic_k_7_2_1_5_answers_patch_with_valid_if_match_emits_fresh_tags():
    """Section 7.2.1.5 — Answers PATCH with valid If-Match emits fresh tags (screen scope)."""
    client = TestClient(create_app())
    # Baseline GET to capture current tag
    baseline = client.get("/api/v1/response-sets/rs_001/screens/welcome")
    baseline_tag = baseline.headers.get("ETag")
    assert isinstance(baseline_tag, str) and len(baseline_tag) > 0

    # Perform write with If-Match set to baseline
    r = client.patch(
        "/api/v1/response-sets/rs_001/answers/q_001",
        headers={"If-Match": baseline_tag},
        json={"value": "A"},
    )

    # Assert: PATCH response status is 200
    assert r.status_code == 200
    # Assert: Headers "Screen-ETag" and "ETag" exist and are non-empty
    s_tag = r.headers.get("Screen-ETag")
    g_tag = r.headers.get("ETag")
    assert isinstance(s_tag, str) and len(s_tag) > 0
    assert isinstance(g_tag, str) and len(g_tag) > 0
    # Assert: parity between Screen-ETag and ETag
    assert s_tag == g_tag
    # Assert: fresh tag different from baseline
    assert g_tag != baseline_tag


def test_epic_k_7_2_1_6_answers_patch_body_mirror_keeps_parity():
    """Section 7.2.1.6 — Answers PATCH keeps header–body parity for screen_view.etag."""
    client = TestClient(create_app())
    # Baseline: GET screen to capture current ETag for parity and valid write
    g = client.get("/api/v1/response-sets/rs_001/screens/welcome")
    baseline_etag = g.headers.get("ETag")
    assert isinstance(baseline_etag, str) and len(baseline_etag) > 0  # captured baseline

    # Perform PATCH with If-Match set to the baseline ETag
    r = client.patch(
        "/api/v1/response-sets/rs_001/answers/q_001",
        headers={"If-Match": baseline_etag},  # remove hard-coded literal; use captured value
        json={"value": "B"},
    )

    # Assert: Response HTTP status is 200
    assert r.status_code == 200
    # Assert: Body screen_view.etag exists and non-empty
    body = r.json() if (r.headers.get("content-type") or "").startswith("application/json") else {}
    body_etag = (body or {}).get("screen_view", {}).get("etag")
    assert isinstance(body_etag, str) and len(body_etag) > 0
    # Assert: Header Screen-ETag exists and non-empty
    header_etag = r.headers.get("Screen-ETag")
    assert isinstance(header_etag, str) and len(header_etag) > 0
    # Assert: equality between header and body mirror per spec
    assert body_etag == header_etag


def test_epic_k_7_2_1_7_document_write_success_emits_domain_and_generic_tags():
    """Section 7.2.1.7 — Document write success emits domain + generic tags (parity)."""
    client = TestClient(create_app())
    # Baseline: GET document to capture current ETag for valid write
    g = client.get("/api/v1/documents/doc_001")
    baseline_etag = g.headers.get("ETag")
    assert isinstance(baseline_etag, str) and len(baseline_etag) > 0  # captured baseline

    # Perform PATCH with If-Match set to the baseline ETag
    r = client.patch(
        "/api/v1/documents/doc_001",
        headers={"If-Match": baseline_etag},  # remove hard-coded literal; use captured value
        json={"title": "Revised"},
    )

    # Assert: Response HTTP status is 200
    assert r.status_code == 200
    # Assert: Header "Document-ETag" exists and non-empty
    d_tag = r.headers.get("Document-ETag")
    assert isinstance(d_tag, str) and len(d_tag) > 0
    # Assert: Header "ETag" exists and non-empty
    g_tag = r.headers.get("ETag")
    assert isinstance(g_tag, str) and len(g_tag) > 0
    # Assert: parity (Document-ETag equals generic ETag)
    assert d_tag == g_tag


def test_epic_k_7_2_1_8_questionnaire_csv_export_emits_questionnaire_tag_parity_with_etag():
    """Section 7.2.1.8 — Questionnaire CSV export emits questionnaire tag (parity with ETag)."""
    client = TestClient(create_app())
    resp = client.get("/api/v1/questionnaires/qq_001/export.csv")

    # Assert: Response HTTP status is 200
    assert resp.status_code == 200
    # Assert: Header "Questionnaire-ETag" exists and non-empty
    q_tag = resp.headers.get("Questionnaire-ETag")
    assert isinstance(q_tag, str) and len(q_tag) > 0
    # Assert: Header "ETag" exists and non-empty
    g_tag = resp.headers.get("ETag")
    assert isinstance(g_tag, str) and len(g_tag) > 0
    # Assert: parity
    assert q_tag == g_tag
    # Assert: Content-Type begins with text/csv
    ct = resp.headers.get("Content-Type") or resp.headers.get("content-type")
    assert isinstance(ct, str) and ct.lower().startswith("text/csv")


def test_epic_k_7_2_1_9_placeholders_get_returns_body_etag_and_generic_header_parity():
    """Section 7.2.1.9 — Placeholders GET returns body etag and generic header (parity)."""
    client = TestClient(create_app())
    resp = client.get("/api/v1/questions/q_123/placeholders")

    # Assert: Response HTTP status is 200
    assert resp.status_code == 200
    # Assert: Body path "placeholders.etag" exists and non-empty
    body_etag = (resp.json() or {}).get("placeholders", {}).get("etag")
    assert isinstance(body_etag, str) and len(body_etag) > 0
    # Assert: Header "ETag" exists and non-empty
    g_tag = resp.headers.get("ETag")
    assert isinstance(g_tag, str) and len(g_tag) > 0
    # Assert: parity
    assert body_etag == g_tag


def test_epic_k_7_2_1_10_placeholders_bind_unbind_success_emits_generic_only():
    """Section 7.2.1.10 — Placeholders bind/unbind success emits generic tag only (no domain headers)."""
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/placeholders/bind",
        json={"question_id": "q_123", "placeholder_id": "ph_001"},
    )

    # Assert: Response HTTP status is 200
    assert resp.status_code == 200
    # Assert: Header ETag exists and is non-empty
    et = resp.headers.get("ETag")
    assert isinstance(et, str) and len(et) > 0
    # Assert: Domain headers are absent
    hdrs = resp.headers
    assert hdrs.get("Screen-ETag") is None
    assert hdrs.get("Question-ETag") is None
    assert hdrs.get("Questionnaire-ETag") is None
    assert hdrs.get("Document-ETag") is None


def test_epic_k_7_2_1_11_authoring_writes_succeed_without_if_match_phase0():
    """Section 7.2.1.11 — Authoring writes succeed without If-Match (Phase‑0)."""
    client = TestClient(create_app())
    resp = client.patch(
        "/api/v1/authoring/screens/welcome",
        json={"title": "Hello"},
    )

    # Assert: Response HTTP status is 200
    assert resp.status_code == 200
    # Assert: Domain header present and non-empty
    domain = resp.headers.get("Screen-ETag") or resp.headers.get("Question-ETag")
    assert isinstance(domain, str) and len(domain) > 0
    # Assert: Generic ETag absent
    assert resp.headers.get("ETag") is None


def test_epic_k_7_2_1_12_domain_header_matches_resource_scope_on_success():
    """Section 7.2.1.12 — Domain header matches resource scope on success (screen/question/questionnaire/document)."""
    client = TestClient(create_app())
    # Screen GET
    r_screen = client.get("/api/v1/response-sets/rs_001/screens/welcome")
    assert isinstance(r_screen.headers.get("Screen-ETag"), str)
    assert r_screen.headers.get("Question-ETag") is None
    assert r_screen.headers.get("Questionnaire-ETag") is None
    assert r_screen.headers.get("Document-ETag") is None

    # Question GET (authoring)
    r_question = client.get("/api/v1/authoring/questions/q_123")
    assert isinstance(r_question.headers.get("Question-ETag"), str)
    assert r_question.headers.get("Screen-ETag") is None
    assert r_question.headers.get("Questionnaire-ETag") is None
    assert r_question.headers.get("Document-ETag") is None

    # Questionnaire CSV
    r_csv = client.get("/api/v1/questionnaires/qq_001/export.csv")
    assert isinstance(r_csv.headers.get("Questionnaire-ETag"), str)
    assert r_csv.headers.get("Screen-ETag") is None
    assert r_csv.headers.get("Question-ETag") is None
    assert r_csv.headers.get("Document-ETag") is None

    # Document GET
    r_doc = client.get("/api/v1/documents/doc_001")
    assert isinstance(r_doc.headers.get("Document-ETag"), str)
    assert r_doc.headers.get("Screen-ETag") is None
    assert r_doc.headers.get("Question-ETag") is None
    assert r_doc.headers.get("Questionnaire-ETag") is None


def test_epic_k_7_2_1_13_cors_exposes_domain_headers_on_authoring_reads():
    """Section 7.2.1.13 — CORS exposes domain headers on authoring reads (no generic ETag)."""
    resp = TestClient(create_app()).get("/api/v1/authoring/screens/welcome")

    # Assert: Status is 200
    assert resp.status_code == 200
    # Assert: Domain header exists and generic ETag absent
    hdrs = resp.headers
    domain_name = "Screen-ETag" if hdrs.get("Screen-ETag") else "Question-ETag"
    domain_val = hdrs.get(domain_name)
    assert isinstance(domain_val, str) and len(domain_val) > 0
    assert hdrs.get("ETag") is None
    # Assert: Access-Control-Expose-Headers includes the domain header (case-insensitive)
    aceh = hdrs.get("Access-Control-Expose-Headers") or ""
    assert domain_name.lower() in aceh.lower()


def test_epic_k_7_2_1_14_cors_exposes_questionnaire_etag_on_csv_export():
    """Section 7.2.1.14 — CORS exposes Questionnaire-ETag on CSV export (and ETag)."""
    resp = TestClient(create_app()).get("/api/v1/questionnaires/qq_001/export.csv")

    # Assert: Status is 200
    assert resp.status_code == 200
    # Assert: Content-Type starts with text/csv
    ct = resp.headers.get("Content-Type") or resp.headers.get("content-type")
    assert isinstance(ct, str) and ct.lower().startswith("text/csv")
    # Assert: Questionnaire-ETag and ETag exist, are equal, and non-empty
    q_tag = resp.headers.get("Questionnaire-ETag")
    g_tag = resp.headers.get("ETag")
    assert isinstance(q_tag, str) and len(q_tag) > 0
    assert isinstance(g_tag, str) and len(g_tag) > 0
    assert q_tag == g_tag
    # Assert: Access-Control-Expose-Headers includes both names, case-insensitive
    aceh = (resp.headers.get("Access-Control-Expose-Headers") or "").lower()
    assert "questionnaire-etag" in aceh and "etag" in aceh


def test_epic_k_7_2_1_15_preflight_allows_if_match_on_write_routes():
    """Section 7.2.1.15 — Preflight allows If-Match on write routes."""
    # Preflight for answers write endpoint
    preflight = TestClient(create_app()).options(
        "/api/v1/response-sets/rs_001/answers/q_001",
        headers={
            "Origin": "https://app.example.test",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "If-Match, Content-Type",
        },
    )
    # Assert: Status is 204 (or success status)
    assert preflight.status_code == 204
    # Assert: Allow-Methods includes PATCH
    acm = (preflight.headers.get("Access-Control-Allow-Methods") or "").upper()
    assert "PATCH" in acm
    # Assert: Allow-Headers includes if-match and content-type (case-insensitive)
    ach = (preflight.headers.get("Access-Control-Allow-Headers") or "").lower()
    assert "if-match" in ach and "content-type" in ach

    # Negative control: authoring GET route preflight need not include if-match
    preflight_auth = TestClient(create_app()).options(
        "/api/v1/authoring/screens/welcome",
        headers={
            "Origin": "https://app.example.test",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Assert: Still succeeds (204 or similar)
    assert preflight_auth.status_code == 204
    # Assert: Allow-Headers may not include if-match
    ach2 = (preflight_auth.headers.get("Access-Control-Allow-Headers") or "").lower()
    assert "if-match" not in ach2


# ---------------------------------------------------------------------------
# 7.2.2.80 / 7.2.2.81 — Required missing tests
# ---------------------------------------------------------------------------


def test_epic_k_7_2_2_80_problem_title_present_on_404():
    """Section 7.2.2.80 — Problem+JSON title is present and surfaced to the user (404)."""
    client = TestClient(create_app())
    r = client.get("/api/v1/documents/missing")
    expected = _error_mode_for_section("7.2.2.80")
    # Assert: Status code is exactly 404 per spec
    assert r.status_code == 404
    # Assert: Content-Type is application/problem+json
    assert "application/problem+json" in (r.headers.get("content-type") or "")
    # Assert: Problem JSON has non-empty title and exact Error Mode code
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    title = body.get("title")
    assert isinstance(title, str) and len(title.strip()) > 0
    assert body.get("code") == expected
    # Assert: Meta invariants when present (request_id optional string, non-negative latency)
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)


def test_epic_k_7_2_2_81_problem_detail_present_on_500():
    """Section 7.2.2.81 — Problem+JSON detail is present and surfaced to the user (500)."""
    client = TestClient(create_app())
    r = client.post("/api/v1/settings", json={"dark": True})
    expected = _error_mode_for_section("7.2.2.81")
    # Assert: Status code is exactly 500 per spec
    assert r.status_code == 500
    # Assert: Content-Type is application/problem+json
    assert "application/problem+json" in (r.headers.get("content-type") or "")
    # Assert: Problem JSON has non-empty detail and exact Error Mode code
    body = {}
    try:
        body = r.json()
    except Exception:
        body = {}
    detail = body.get("detail")
    assert isinstance(detail, str) and len(detail.strip()) > 0
    assert body.get("code") == expected
    # Assert: Meta invariants when present (request_id optional string, non-negative latency)
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)


# ---------------------------------------------------------------------------
# 7.2.2.82–7.2.2.89 — Missing per Clarke; add problem invariants + code tests
# ---------------------------------------------------------------------------


def test_epic_k_7_2_2_82_problem_invariants_and_code(mocker):
    """Section 7.2.2.82 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.82")
    # Assert: Content-Type includes application/problem+json
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: Body JSON contains exact Error Mode code for this section
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    # Assert: Problem payload must not include an "output" field
    assert "output" not in body
    # Assert: Meta invariants — request_id optionally present, latency non-negative when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


def test_epic_k_7_2_2_83_problem_invariants_and_code(mocker):
    """Section 7.2.2.83 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.83")
    # Assert: Content-Type includes application/problem+json
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: Body JSON contains exact Error Mode code for this section
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    # Assert: Problem payload must not include an "output" field
    assert "output" not in body
    # Assert: Meta invariants — request_id optionally present, latency non-negative when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


def test_epic_k_7_2_2_84_problem_invariants_and_code(mocker):
    """Section 7.2.2.84 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.84")
    # Assert: Content-Type includes application/problem+json
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: Body JSON contains exact Error Mode code for this section
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    # Assert: Problem payload must not include an "output" field
    assert "output" not in body
    # Assert: Meta invariants — request_id optionally present, latency non-negative when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


def test_epic_k_7_2_2_85_problem_invariants_and_code(mocker):
    """Section 7.2.2.85 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.85")
    # Assert: Content-Type includes application/problem+json
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: Body JSON contains exact Error Mode code for this section
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    # Assert: Problem payload must not include an "output" field
    assert "output" not in body
    # Assert: Meta invariants — request_id optionally present, latency non-negative when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


def test_epic_k_7_2_2_86_problem_invariants_and_code(mocker):
    """Section 7.2.2.86 — Verifies problem+json invariants and Error Mode code from spec."""
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.86")
    # Assert: Content-Type includes application/problem+json
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    # Assert: Body JSON contains exact Error Mode code for this section
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    # Assert: tag exposure headers are present and non-empty
    etag = r.headers.get("ETag")
    screen_etag = r.headers.get("Screen-ETag")
    assert isinstance(etag, str) and etag.strip() != ""
    assert isinstance(screen_etag, str) and screen_etag.strip() != ""
    # Assert: Access-Control-Expose-Headers contains both exactly once
    aceh = r.headers.get("Access-Control-Expose-Headers", "")
    items = [x.strip().lower() for x in aceh.split(",") if x.strip()]
    assert items.count("etag") == 1
    assert items.count("screen-etag") == 1
    # Assert: Problem payload must not include an "output" field
    assert "output" not in body
    # Assert: Meta invariants — request_id optionally present, latency non-negative when present
    meta = (body.get("meta") or {})
    rid = meta.get("request_id")
    assert (rid is None) or (isinstance(rid, str) and len(rid) > 0)
    lat = meta.get("latency_ms")
    assert (lat is None) or (isinstance(lat, (int, float)) and lat >= 0)
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")


def test_epic_k_7_2_2_87_request_content_type_unsupported(mocker):
    """Section 7.2.2.87 — Unsupported Content-Type yields 415 with PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED.

    Sends text/plain body and asserts repository boundaries were not invoked.
    """
    client = TestClient(create_app())
    # Repo spies must not be invoked for content-type validation failure
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="ignored")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=0)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={
            "Authorization": "Bearer dev-token",
            "If-Match": 'W/"abc"',
            "Content-Type": "text/plain",
        },
        data="raw body that is not JSON",
    )
    expected = _error_mode_for_section("7.2.2.87")
    # Assert: status 415 Unsupported Media Type
    assert r.status_code == 415
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: error code matches PRE_REQUEST_CONTENT_TYPE_UNSUPPORTED and includes message
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    # Assert: repositories were not touched
    m_key.assert_not_called()
    m_ver.assert_not_called()


def test_epic_k_7_2_2_88_documents_reorder_precondition_failure_emits_diagnostics(mocker):
    """Section 7.2.2.88 — Documents reorder with stale If-Match yields 412 and diagnostic headers.

    Asserts X-List-ETag and X-If-Match-Normalized presence and values.
    """
    client = TestClient(create_app())
    # Repo boundaries are not used for document reorder; verify not called
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="ignored")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=0)
    # Use a deliberately awkward If-Match value to exercise normalisation
    raw_if_match = 'W/"  StaleTag  "\t'
    r = client.patch(
        "/api/v1/documents/reorder",
        headers={"If-Match": raw_if_match},
        json={"order": ["doc_b", "doc_a"], "list_id": "list_1"},
    )
    expected = _error_mode_for_section("7.2.2.88")
    # Assert: 412 Precondition Failed for document routes on mismatch
    assert r.status_code == 412
    # Assert: problem+json content-type
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: error code and presence of human-readable message
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    # Assert: diagnostic headers present
    list_etag = r.headers.get("X-List-ETag")
    assert isinstance(list_etag, str) and list_etag.strip() != ""
    norm = r.headers.get("X-If-Match-Normalized")
    assert isinstance(norm, str) and norm.strip() != ""
    # Assert: normalized value reflects canonical token
    assert norm == "StaleTag"
    m_key.assert_not_called()
    m_ver.assert_not_called()


def test_epic_k_7_2_2_89_expose_headers_contains_domain_and_generic_once(mocker):
    """Section 7.2.2.89 — Access-Control-Expose-Headers includes ETag and Screen-ETag exactly once.

    Also asserts both headers are present and non-empty on the response.
    """
    client = TestClient(create_app())
    m_key = mocker.patch("app.logic.repository_screens.get_screen_key_for_question", return_value="welcome")
    m_ver = mocker.patch("app.logic.repository_answers.get_screen_version", return_value=1)
    r = client.patch(
        "/api/v1/response-sets/resp_123/answers/q_456",
        headers={"Authorization": "Bearer dev-token", "If-Match": 'W/"mismatch"'},
        json={"value": "x"},
    )
    expected = _error_mode_for_section("7.2.2.89")
    # Assert: problem+json and error code presence
    ctype = r.headers.get("content-type", "")
    assert "application/problem+json" in ctype
    # Assert: exact HTTP status equals mapping for this section's Error Mode
    expected_status = _expected_status_for_error_code(expected)
    assert r.status_code == expected_status
    try:
        body = r.json()
    except Exception:
        body = {}
    assert body.get("code") == expected
    # Assert: human-readable message is present and non-empty
    msg = body.get("message")
    assert isinstance(msg, str) and msg.strip() != ""
    # Assert: header presence and exposure list contains both exactly once
    etag = r.headers.get("ETag")
    screen_etag = r.headers.get("Screen-ETag")
    assert isinstance(etag, str) and etag.strip() != ""
    assert isinstance(screen_etag, str) and screen_etag.strip() != ""
    aceh = r.headers.get("Access-Control-Expose-Headers", "")
    items = [x.strip().lower() for x in aceh.split(",") if x.strip()]
    assert items.count("etag") == 1
    assert items.count("screen-etag") == 1
    m_key.assert_called_with("q_456")
    m_ver.assert_called_with("resp_123", "welcome")

# ---------------------------------------------------------------------------
# 7.3.1.x — Behavioural tests (client/orchestrator sequencing)
# ---------------------------------------------------------------------------


def test_epic_k_7_3_1_1_load_screen_view_after_run_start():
    """Section 7.3.1.1 — Response set creation triggers initial screen load."""
    trace = invoke_orchestrator_trace("7.3.1.1")
    names = _event_names(trace)
    # Assert: screen view fetch invoked once immediately after response set creation completes
    assert names.count("screen_view_fetch") == 1
    assert _idx(names, "screen_view_fetch") == _idx(names, "response_set_created") + 1


def test_epic_k_7_3_1_2_store_hydration_after_screen_view_fetch():
    """Section 7.3.1.2 — Screen view fetch triggers store hydration."""
    trace = invoke_orchestrator_trace("7.3.1.2")
    names = _event_names(trace)
    # Assert: store hydration invoked once immediately after screen view fetch completes
    assert names.count("store_hydration") == 1
    assert _idx(names, "store_hydration") == _idx(names, "screen_view_fetch") + 1


def test_epic_k_7_3_1_3_autosave_subscriber_activation_after_hydration():
    """Section 7.3.1.3 — Store hydration triggers autosave subscriber start."""
    trace = invoke_orchestrator_trace("7.3.1.3")
    names = _event_names(trace)
    # Assert: autosave starts once immediately after store hydration completes
    assert names.count("autosave_subscriber_start") == 1
    assert _idx(names, "autosave_subscriber_start") == _idx(names, "store_hydration") + 1


def test_epic_k_7_3_1_4_debounced_save_triggers_patch():
    """Section 7.3.1.4 — Debounced local change triggers PATCH call."""
    trace = invoke_orchestrator_trace("7.3.1.4")
    names = _event_names(trace)
    # Assert: PATCH invoked once immediately after debounce window completes
    assert names.count("answers_patch_call") == 1
    assert _idx(names, "answers_patch_call") == _idx(names, "debounce_window_complete") + 1


def test_epic_k_7_3_1_5_successful_patch_triggers_screen_apply():
    """Section 7.3.1.5 — PATCH success triggers screen apply."""
    trace = invoke_orchestrator_trace("7.3.1.5")
    names = _event_names(trace)
    # Assert: screen apply invoked once immediately after PATCH success
    assert names.count("screen_apply") == 1
    assert _idx(names, "screen_apply") == _idx(names, "answers_patch_success") + 1


def test_epic_k_7_3_1_6_binding_success_triggers_screen_refresh():
    """Section 7.3.1.6 — Bind/unbind success triggers screen refresh apply."""
    trace = invoke_orchestrator_trace("7.3.1.6")
    names = _event_names(trace)
    # Assert: screen refresh apply invoked once immediately after bind/unbind success
    assert names.count("screen_refresh_apply") == 1
    assert _idx(names, "screen_refresh_apply") == _idx(names, "bind_unbind_success") + 1


def test_epic_k_7_3_1_7_active_screen_change_rotates_working_tag():
    """Section 7.3.1.7 — Active screen change rotates working tag."""
    trace = invoke_orchestrator_trace("7.3.1.7")
    names = _event_names(trace)
    # Assert: working tag rotation invoked once immediately after active screen change
    assert names.count("working_tag_rotation") == 1
    assert _idx(names, "working_tag_rotation") == _idx(names, "active_screen_change") + 1


def test_epic_k_7_3_1_8_short_poll_tick_triggers_conditional_refresh():
    """Section 7.3.1.8 — Poll tick ETag change triggers screen load."""
    trace = invoke_orchestrator_trace("7.3.1.8")
    names = _event_names(trace)
    # Assert: screen load invoked once immediately after detecting tag change
    assert names.count("screen_load") == 1
    assert _idx(names, "screen_load") == _idx(names, "poll_tick_etag_changed") + 1


def test_epic_k_7_3_1_9_tab_focus_triggers_conditional_refresh():
    """Section 7.3.1.9 — Tab focus triggers light refresh step."""
    trace = invoke_orchestrator_trace("7.3.1.9")
    names = _event_names(trace)
    # Assert: light refresh invoked once immediately after tab visibility handling
    assert names.count("light_refresh") == 1
    assert _idx(names, "light_refresh") == _idx(names, "tab_visible") + 1


def test_epic_k_7_3_1_10_multi_scope_headers_trigger_store_updates():
    """Section 7.3.1.10 — Multi-scope headers trigger per-scope updates."""
    trace = invoke_orchestrator_trace("7.3.1.10")
    names = _event_names(trace)
    # Assert: per-scope ETag store update invoked once immediately after success response
    assert names.count("per_scope_etag_store_update") == 1
    assert _idx(names, "per_scope_etag_store_update") == _idx(names, "write_success_with_multi_scope_headers") + 1


def test_epic_k_7_3_1_11_inject_fresh_if_match_after_header_update():
    """Section 7.3.1.11 — Per-scope update triggers next-write header injection."""
    trace = invoke_orchestrator_trace("7.3.1.11")
    names = _event_names(trace)
    # Assert: header injection occurs once immediately after per-scope store update
    assert names.count("inject_fresh_if_match_next_write") == 1
    assert _idx(names, "inject_fresh_if_match_next_write") == _idx(names, "per_scope_etag_store_update") + 1


def test_epic_k_7_3_1_12_continue_polling_after_304():
    """Section 7.3.1.12 — Light refresh 304 continues polling loop."""
    trace = invoke_orchestrator_trace("7.3.1.12")
    names = _event_names(trace)
    # Assert: polling continue invoked once immediately after handling 304
    assert names.count("polling_continue") == 1
    assert _idx(names, "polling_continue") == _idx(names, "light_refresh_304") + 1


def test_epic_k_7_3_1_13_answers_post_success_triggers_screen_apply():
    """Section 7.3.1.13 — POST success triggers screen apply."""
    trace = invoke_orchestrator_trace("7.3.1.13")
    names = _event_names(trace)
    # Assert: screen apply invoked once immediately after POST success
    assert names.count("screen_apply") == 1
    assert _idx(names, "screen_apply") == _idx(names, "answers_post_success") + 1


def test_epic_k_7_3_1_14_answers_delete_success_triggers_screen_apply():
    """Section 7.3.1.14 — DELETE success triggers screen apply."""
    trace = invoke_orchestrator_trace("7.3.1.14")
    names = _event_names(trace)
    # Assert: screen apply invoked once immediately after DELETE success
    assert names.count("screen_apply") == 1
    assert _idx(names, "screen_apply") == _idx(names, "answers_delete_success") + 1


def test_epic_k_7_3_1_15_document_reorder_success_triggers_list_refresh():
    """Section 7.3.1.15 — Reorder success triggers document list refresh/apply."""
    trace = invoke_orchestrator_trace("7.3.1.15")
    names = _event_names(trace)
    # Assert: document list refresh/apply invoked once immediately after reorder success
    assert names.count("document_list_refresh_apply") == 1
    assert _idx(names, "document_list_refresh_apply") == _idx(names, "document_reorder_success") + 1


def test_epic_k_7_3_1_16_any_match_precondition_success_triggers_mutation():
    """Section 7.3.1.16 — Any-match guard success triggers mutation."""
    trace = invoke_orchestrator_trace("7.3.1.16")
    names = _event_names(trace)
    # Assert: mutation invoked once immediately after any-match precondition success
    assert names.count("mutation_invoked") == 1
    assert _idx(names, "mutation_invoked") == _idx(names, "precondition_guard_any_match_success") + 1


def test_epic_k_7_3_1_17_wildcard_precondition_success_triggers_mutation():
    """Section 7.3.1.17 — Wildcard precondition success triggers mutation."""
    trace = invoke_orchestrator_trace("7.3.1.17")
    names = _event_names(trace)
    # Assert: mutation invoked once immediately after wildcard precondition success
    assert names.count("mutation_invoked") == 1
    assert _idx(names, "mutation_invoked") == _idx(names, "precondition_guard_wildcard_success") + 1


def test_epic_k_7_3_1_18_runtime_json_success_triggers_header_read():
    """Section 7.3.1.18 — Runtime success triggers client header-read/tag handling."""
    trace = invoke_orchestrator_trace("7.3.1.18")
    names = _event_names(trace)
    # Assert: client header-read invoked once immediately after runtime JSON success
    assert names.count("client_header_read") == 1
    assert _idx(names, "client_header_read") == _idx(names, "runtime_json_success") + 1


def test_epic_k_7_3_1_19_authoring_json_success_triggers_header_read():
    """Section 7.3.1.19 — Authoring success triggers client header-read/tag handling."""
    trace = invoke_orchestrator_trace("7.3.1.19")
    names = _event_names(trace)
    # Assert: client header-read invoked once immediately after authoring JSON success
    assert names.count("client_header_read") == 1
    assert _idx(names, "client_header_read") == _idx(names, "authoring_json_success") + 1


def test_epic_k_7_3_1_20_non_json_download_triggers_tag_handling_without_apply():
    """Section 7.3.1.20 — Download success triggers tag handling; no screen/list apply."""
    trace = invoke_orchestrator_trace("7.3.1.20")
    names = _event_names(trace)
    # Assert: tag handling invoked once immediately after download handling completes
    assert names.count("tag_handling") == 1
    assert _idx(names, "tag_handling") == _idx(names, "csv_download_success") + 1
    # Assert: no screen/list apply occurs for non-JSON download
    assert "screen_apply" not in names
    assert "list_apply" not in names


def test_epic_k_7_3_1_21_successful_guarded_write_logs_in_order():
    """Section 7.3.1.21 — Guarded write success triggers emit-logging after mutation."""
    trace = invoke_orchestrator_trace("7.3.1.21")
    names = _event_names(trace)
    # Assert: emit-logging invoked once immediately after mutation completes
    assert names.count("emit_logging") == 1
    assert _idx(names, "emit_logging") == _idx(names, "mutation_complete") + 1


def test_epic_k_7_3_1_22_legacy_token_parity_does_not_trigger_extra_refresh():
    """Section 7.3.1.22 — Unchanged legacy token does not trigger extra refresh/rotation."""
    trace = invoke_orchestrator_trace("7.3.1.22")
    names = _event_names(trace)
    # Assert: detector invoked once immediately after screen GET completes
    assert names.count("legacy_token_parity_detector") == 1
    assert _idx(names, "legacy_token_parity_detector") == _idx(names, "screen_get_complete") + 1
    # Assert: no additional refresh triggered
    assert "additional_refresh" not in names


# ---------------------------------------------------------------------------
# 7.3.2.x — Behavioural tests (environmental fault scenarios)
# ---------------------------------------------------------------------------


def test_epic_k_7_3_2_1_cors_expose_headers_misconfiguration_halts_at_step4():
    """Section 7.3.2.1 — CORS expose-headers misconfig halts at STEP-4; prevents STEP-5."""
    trace = invoke_orchestrator_trace("7.3.2.1")
    names = _event_names(trace)
    diags = trace.get("diagnostics", {})
    telemetry = trace.get("telemetry", [])
    # Assert: error handler invoked once immediately when STEP-4 header emission raises
    assert names.count("error_handler") == 1
    assert _idx(names, "error_handler") == _idx(names, "step_4_header_emit") + 1
    # Assert: STEP-5 body mirrors prevented
    assert "step_5_body_mirrors" not in names
    # Assert: condition classified as ENV_CORS_EXPOSE_HEADERS_MISCONFIGURED
    assert diags.get("error_mode") == "ENV_CORS_EXPOSE_HEADERS_MISCONFIGURED"
    # Assert: no retries of STEP-4 and no partial header writes (no duplicate emissions)
    assert names.count("step_4_header_emit") == 1
    # Assert: one error telemetry event is emitted for this condition
    assert len([t for t in telemetry if t.get("code") == "ENV_CORS_EXPOSE_HEADERS_MISCONFIGURED"]) == 1


def test_epic_k_7_3_2_2_logging_sink_unavailable_during_precondition_does_not_alter_flow():
    """Section 7.3.2.2 — Telemetry failure during STEP-2 does not alter flow."""
    trace = invoke_orchestrator_trace("7.3.2.2")
    names = _event_names(trace)
    diags = trace.get("diagnostics", {})
    telemetry = trace.get("telemetry", [])
    # Assert: STEP-3 mutation invoked once immediately after STEP-2 precondition completes
    assert names.count("step_3_mutation") == 1
    assert _idx(names, "step_3_mutation") == _idx(names, "step_2_precondition_enforce") + 1
    # Assert: STEP-4 header emission invoked once after STEP-3
    assert names.count("step_4_header_emit") == 1
    assert _idx(names, "step_4_header_emit") == _idx(names, "step_3_mutation") + 1
    # Assert: STEP-5 body mirrors invoked once after STEP-4
    assert names.count("step_5_body_mirrors") == 1
    assert _idx(names, "step_5_body_mirrors") == _idx(names, "step_4_header_emit") + 1
    # Assert: exactly one failed attempt to write etag.enforce was made; no retries
    assert len([t for t in telemetry if t.get("code") == "ENV_LOGGING_SINK_UNAVAILABLE_ENFORCE"]) == 1
    # Assert: classification recorded in diagnostics
    assert diags.get("error_mode") == "ENV_LOGGING_SINK_UNAVAILABLE_ENFORCE"


def test_epic_k_7_3_2_3_logging_sink_unavailable_during_header_emit_does_not_block_finalisation():
    """Section 7.3.2.3 — Telemetry failure during STEP-4 does not block finalisation."""
    trace = invoke_orchestrator_trace("7.3.2.3")
    names = _event_names(trace)
    telemetry = trace.get("telemetry", [])
    diags = trace.get("diagnostics", {})
    # Assert: STEP-4 header emission completes and immediately triggers response finalisation
    assert names.count("finalise_response") == 1
    assert _idx(names, "finalise_response") == _idx(names, "step_4_header_emit") + 1
    # Assert: STEP-5 body mirrors invoked once immediately after finalisation
    assert names.count("step_5_body_mirrors") == 1
    assert _idx(names, "step_5_body_mirrors") == _idx(names, "finalise_response") + 1
    # Assert: exactly one failed attempt to write etag.emit; no retries
    assert len([t for t in telemetry if t.get("code") == "ENV_LOGGING_SINK_UNAVAILABLE_EMIT"]) == 1
    # Assert: classification recorded as degraded telemetry only
    assert diags.get("error_mode") == "ENV_LOGGING_SINK_UNAVAILABLE_EMIT"


def test_epic_k_7_3_2_4_proxy_strips_domain_etag_headers_halts_at_step4():
    """Section 7.3.2.4 — Egress policy stripping domain ETags halts at STEP-4; prevents STEP-5 and finalisation."""
    trace = invoke_orchestrator_trace("7.3.2.4")
    names = _event_names(trace)
    diags = trace.get("diagnostics", {})
    # Assert: STEP-4 detection halts once immediately
    assert names.count("step_4_halt_due_to_egress_strip") == 1
    assert _idx(names, "step_4_halt_due_to_egress_strip") == _idx(names, "step_4_header_emit") + 1
    # Assert: STEP-5 body mirrors prevented; response finalisation prevented
    assert "step_5_body_mirrors" not in names
    assert "finalise_response" not in names
    # Assert: classification
    assert diags.get("error_mode") == "ENV_PROXY_STRIPS_DOMAIN_ETAG_HEADERS"
    # Assert: no retries of STEP-4
    assert names.count("step_4_header_emit") == 1


def test_epic_k_7_3_2_5_preflight_missing_if_match_blocks_before_step2():
    """Section 7.3.2.5 — OPTIONS preflight omitting If-Match blocks before STEP-2."""
    trace = invoke_orchestrator_trace("7.3.2.5")
    names = _event_names(trace)
    diags = trace.get("diagnostics", {})
    # Assert: pipeline halts during preflight before STEP-2
    assert names.count("preflight_halt") == 1
    assert diags.get("halted_at") in {"PREFLIGHT", "STEP_1"}
    # Assert: STEP-2/3/4/5 prevented
    assert "step_2_precondition_enforce" not in names
    assert "step_3_mutation" not in names
    assert "step_4_header_emit" not in names
    assert "step_5_body_mirrors" not in names
    # Assert: classification code
    assert diags.get("error_mode") == "ENV_CORS_ALLOW_HEADERS_MISSING_IF_MATCH"


def test_epic_k_7_3_2_6_proxy_strips_if_match_on_ingress_halts_at_step2_missing_precondition():
    """Section 7.3.2.6 — Ingress strips If-Match → guard missing-precondition branch; mutation prevented."""
    trace = invoke_orchestrator_trace("7.3.2.6")
    names = _event_names(trace)
    diags = trace.get("diagnostics", {})
    # Assert: STEP-2 invoked once and halts immediately on missing-precondition branch
    assert names.count("step_2_precondition_enforce") == 1
    assert names.count("missing_precondition_branch") == 1
    assert _idx(names, "missing_precondition_branch") == _idx(names, "step_2_precondition_enforce") + 1
    # Assert: mutation and later steps prevented
    assert "step_3_mutation" not in names
    assert "step_4_header_emit" not in names
    assert "step_5_body_mirrors" not in names
    # Assert: classification
    assert diags.get("error_mode") == "ENV_PROXY_STRIPS_IF_MATCH"


def test_epic_k_7_3_2_7_guard_misapplied_to_read_endpoints_halts_at_step2():
    """Section 7.3.2.7 — Guard misapplied to GET halts at STEP-2; prevents handler and headers."""
    trace = invoke_orchestrator_trace("7.3.2.7")
    names = _event_names(trace)
    diags = trace.get("diagnostics", {})
    # Assert: STEP-2 invoked once (misapplied) and halts immediately
    assert names.count("step_2_precondition_enforce") == 1
    assert names.count("guard_misapplied_halt") == 1
    assert _idx(names, "guard_misapplied_halt") == _idx(names, "step_2_precondition_enforce") + 1
    # Assert: handler, header emission, and mirrors prevented
    assert "handler_execute" not in names
    assert "step_4_header_emit" not in names
    assert "step_5_body_mirrors" not in names
    # Assert: classification
    assert diags.get("error_mode") == "ENV_GUARD_MISAPPLIED_TO_READ_ENDPOINTS"
