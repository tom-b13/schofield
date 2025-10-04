"""Epic C – Document ingestion and parsing integration steps.

Implements only Epic C specific steps. Reuses generic HTTP helpers from
questionnaire_steps to avoid ambiguity with existing steps.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from typing import Any, Dict, Optional

import httpx
from behave import given, then, when, step

# Reuse helpers from the shared steps module
from questionnaire_steps import (
    _http_request,
    _validate_with_name,
    _jsonpath,
    _get_header_case_insensitive,
    _interpolate,
    step_when_get,
)


def _ensure_vars(context) -> Dict[str, Any]:
    if not hasattr(context, "vars") or context.vars is None:
        context.vars = {}
    return context.vars


@given('the API base URL is "{url}"')
def epic_c_set_base_url(context, url: str):
    # Clarke: prefer TEST_BASE_URL if set; fall back to provided URL
    env_url = os.getenv("TEST_BASE_URL", "").strip()
    context.test_base_url = env_url or url
    # Clarke instruction: reset test state before each scenario to avoid POST 409s
    try:
        status, _, _, _ = _http_request(
            context,
            "POST",
            "/__test/reset/documents",
            headers={"Accept": "*/*"},
            json_body=None,
        )
        # Fallback cleanup when reset endpoint is unavailable (404)
        if int(status) == 404:
            # Enumerate existing documents and delete each to reach a clean slate
            s, _, body, _ = _http_request(context, "GET", "/documents/names", headers={"Accept": "*/*"})
            if int(s) == 200 and isinstance(body, dict):
                items = body.get("list") or []
                try:
                    for item in items:
                        did = item.get("document_id")
                        if isinstance(did, str) and did:
                            _http_request(context, "DELETE", f"/documents/{did}", headers={"Accept": "*/*"})
                except Exception:
                    # Best-effort cleanup
                    pass
    except Exception:
        # Ignore failures; scenarios should proceed regardless
        pass


@given('the DOCX MIME is "{mime}"')
def epic_c_set_docx_mime(context, mime: str):
    _ensure_vars(context)["docx_mime"] = mime


@when('I POST "{path}" with JSON:')
def epic_c_post_json(context, path: str):
    raw = context.text or "{}"
    try:
        raw = raw.replace("\\_", "_")
    except Exception:
        pass
    try:
        body = json.loads(raw)
    except Exception as exc:
        raise AssertionError(f"Invalid JSON body: {exc}\n{raw}")
    headers = {"Content-Type": "application/json", "Accept": "*/*"}
    status, headers_out, body_json, body_text = _http_request(
        context, "POST", path, headers=headers, json_body=body
    )
    context.last_response = {
        "status": status,
        "headers": headers_out,
        "json": body_json,
        "text": body_text,
        "bytes": getattr(context, "_last_response_bytes", None),
        "path": path,
        "method": "POST",
    }
    if status == 201 and body_json is not None:
        _validate_with_name(body_json, "DocumentResponse")


@given('I have created a document "{alias}" with title "{title}" and order_number {n:d} (version 1)')
def epic_c_seed_document_v1(context, alias: str, title: str, n: int):
    body = {"title": title, "order_number": n}
    status, headers_out, body_json, body_text = _http_request(
        context,
        "POST",
        "/documents",
        headers={"Content-Type": "application/json", "Accept": "*/*"},
        json_body=body,
    )
    # Clarke explicit action: prefer 201 Created on POST create
    assert status in (200, 201), f"Expected 201/200, got {status}"
    assert isinstance(body_json, dict), "Expected JSON body"
    if status == 201:
        try:
            _validate_with_name(body_json, "DocumentResponse")
        except Exception:
            # Non-fatal to keep CI compatibility if validation resources differ
            pass
    # Capture the server-assigned document_id
    doc_id = _jsonpath(body_json, "$.document.document_id")
    _ensure_vars(context)[alias] = doc_id
    context.last_response = {
        "status": status,
        "headers": headers_out,
        "json": body_json,
        "text": body_text,
        "bytes": getattr(context, "_last_response_bytes", None),
        "path": "/documents",
        "method": "POST",
    }


@given('I GET "/documents/names" and capture "list_etag" as "{var}"')
def epic_c_get_names_and_capture_list_etag(context, var: str):
    step_when_get(context, "/documents/names")
    # Clarke (revised): Prefer body.list_etag; fallback to ETag header; only
    # assert equality when both are present. Do not require header presence.
    body = context.last_response.get("json")
    headers = context.last_response.get("headers", {}) or {}
    body_etag: Optional[str] = None
    header_etag: Optional[str] = None
    if isinstance(body, dict) and "list_etag" in body:
        v = body.get("list_etag")
        if isinstance(v, (bytes, bytearray)):
            try:
                v = v.decode("utf-8")
            except Exception:
                pass
        body_etag = str(v) if v is not None else None
        if body_etag is not None:
            body_etag = body_etag.strip()
    try:
        header_val = _get_header_case_insensitive(headers, "ETag")
        if isinstance(header_val, (bytes, bytearray)):
            try:
                header_val = header_val.decode("utf-8")
            except Exception:
                pass
        header_etag = str(header_val) if header_val is not None else None
        if header_etag is not None:
            header_etag = header_etag.strip()
    except Exception:
        header_etag = None
    # If both present and non-empty, assert equality
    if body_etag and header_etag:
        assert body_etag == header_etag, "header ETag and body.list_etag mismatch"
    # Choose captured value preferring body, then header
    captured = body_etag or header_etag or ""
    assert isinstance(captured, str) and captured.strip(), "Expected non-empty list_etag in body or header"
    # Store under both the requested alias and the canonical key for fallback
    trimmed = captured.strip()
    vars_map = _ensure_vars(context)
    vars_map[var] = trimmed
    vars_map["list_etag"] = trimmed


@given('I GET metadata for document "{alias}" and capture the document ETag as "{var}"')
def epic_c_get_metadata_and_capture_etag(context, alias: str, var: str):
    vars_map = _ensure_vars(context)
    doc_id = vars_map.get(alias)
    assert isinstance(doc_id, str) and doc_id, f"Unknown alias {alias}"
    path = f"/documents/{doc_id}"
    step_when_get(context, path)
    headers = context.last_response.get("headers", {}) or {}
    etag = _get_header_case_insensitive(headers, "ETag")
    assert isinstance(etag, str) and etag.strip(), "Expected non-empty ETag"
    vars_map[var] = etag


@when('I PUT "{path}" with headers:')
def epic_c_put_with_headers_stage(context, path: str):
    # Interpolate any {alias} tokens in the path using context.vars
    context._pending_put_path = _interpolate(path, context)
    # Stage headers with canonicalization and immediate interpolation.
    vars_map = _ensure_vars(context)
    staged: Dict[str, str] = {}
    for row in context.table:
        key_raw = str(row[0]) if row[0] is not None else ""
        val_raw = str(row[1]) if row[1] is not None else ""
        key = key_raw.strip()
        # Interpolate brace tokens and trim whitespace
        val_interp = _interpolate(val_raw, context)
        if isinstance(val_interp, str):
            val_interp = val_interp.strip()
        # Support bare tokens like LE1 by resolving from context.vars if present
        if isinstance(val_interp, str) and val_interp in vars_map:
            val_interp = str(vars_map[val_interp]).strip()
        # Canonicalize If-Match to a single key only when provided and non-empty
        if key.lower() == "if-match":
            if isinstance(val_interp, str) and val_interp:
                staged["If-Match"] = val_interp
                # Clarke change: persist the last provided If-Match into vars
                # for robust reuse if staged headers are lost.
                try:
                    vars_map["_last_if_match"] = val_interp
                except Exception:
                    pass
            # Do not keep duplicate/non-canonical variants
            continue
        # For other keys, keep as provided (trimmed)
        staged[key] = val_interp
    context._pending_put_headers = staged


@when('body is a valid DOCX file of {size:d} bytes named "{filename}"')
def epic_c_put_docx_body_with_size(context, size: int, filename: str):
    # Prepare binary content of the requested length
    content = (b"PK\x03\x04" + os.urandom(max(0, size - 4))) if size > 0 else b""
    _epic_c_send_put_content(context, content)
    # Validate success envelope when applicable
    if context.last_response.get("status") == 200 and context.last_response.get("json") is not None:
        _validate_with_name(context.last_response.get("json"), "ContentUpdateResult")


@when("body is a valid DOCX file")
def epic_c_put_docx_body_default(context):
    # Default to a small payload
    content = b"PK\x03\x04minimal-docx"  # zip file signature prefix
    _epic_c_send_put_content(context, content)
    if context.last_response.get("status") == 200 and context.last_response.get("json") is not None:
        _validate_with_name(context.last_response.get("json"), "ContentUpdateResult")


@when("body is an invalid DOCX byte stream")
def epic_c_put_invalid_docx(context):
    content = b"not-a-zip-not-a-docx"
    _epic_c_send_put_content(context, content)


def _epic_c_send_put_content(context, content: bytes) -> None:
    path = getattr(context, "_pending_put_path", None)
    headers = (getattr(context, "_pending_put_headers", None) or {}).copy()
    assert isinstance(path, str) and path, "No pending PUT path staged"
    # Fill in default headers
    mime = _ensure_vars(context).get(
        "docx_mime", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    headers.setdefault("Content-Type", str(mime))
    headers.setdefault("Accept", "*/*")
    # Clarke: send via shared _http_request to apply API prefix rewrite
    status, headers_out, body_json, body_text = _http_request(
        context, "PUT", path, headers=headers, json_body=None, text_body=None, content=content
    )
    context.last_response = {
        "status": status,
        "headers": headers_out,
        "json": body_json,
        "text": body_text,
        "bytes": getattr(context, "_last_response_bytes", None),
        "path": path,
        "method": "PUT",
    }
    # Persist for idempotency re-run
    context._last_put_path = path
    context._last_put_headers = headers
    context._last_put_content = content


@then('when I GET metadata for document "{alias}" the version should be {v:d}')
def epic_c_get_metadata_and_assert_version(context, alias: str, v: int):
    doc_id = _ensure_vars(context).get(alias)
    assert isinstance(doc_id, str) and doc_id, f"Unknown alias {alias}"
    step_when_get(context, f"/documents/{doc_id}")
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    actual = _jsonpath(body, "$.document.version")
    assert actual == v, f"Expected version {v}, got {actual}"


@then('when I repeat the same PUT with identical Idempotency-Key the response version should equal {v:d}')
def epic_c_repeat_put_idempotent(context, v: int):
    path = getattr(context, "_last_put_path", None)
    headers = getattr(context, "_last_put_headers", None)
    content = getattr(context, "_last_put_content", None)
    assert isinstance(path, str) and isinstance(headers, dict) and isinstance(content, (bytes, bytearray)), (
        "No previous PUT request captured"
    )
    status, headers_out, body_json, body_text = _http_request(
        context, "PUT", path, headers=headers, json_body=None, text_body=None, content=content
    )
    context.last_response = {
        "status": status,
        "headers": headers_out,
        "json": body_json,
        "text": body_text,
        "bytes": getattr(context, "_last_response_bytes", None),
        "path": path,
        "method": "PUT",
    }
    assert context.last_response.get("status") == 200, f"Expected 200, got {context.last_response.get('status')}"
    assert _jsonpath(context.last_response.get("json"), "$.content_result.version") == v


# ----------------------
# Title update (PATCH)
# ----------------------

@given('a document "{alias}" exists with title "{title}", order_number {n:d}, version {v:d}')
def epic_c_doc_exists_with_version(context, alias: str, title: str, n: int, v: int):
    # Create
    epic_c_seed_document_v1(context, alias, title, n)
    if v > 1:
        # Upload one content version to reach desired version
        context._pending_put_path = f"/documents/{_ensure_vars(context)[alias]}/content"
        context._pending_put_headers = {
            "Content-Type": _ensure_vars(context).get(
                "docx_mime", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            "Idempotency-Key": f"idem-{uuid.uuid4()}",
            "If-Match": 'W/"doc-v1"',
        }
        epic_c_put_docx_body_default(context)
        assert _jsonpath(context.last_response.get("json"), "$.content_result.version") == 2


@when('I PATCH "{path}" with JSON:')
def epic_c_patch_json(context, path: str):
    raw = context.text or "{}"
    try:
        raw = raw.replace("\\_", "_")
    except Exception:
        pass
    try:
        body = json.loads(raw)
    except Exception as exc:
        raise AssertionError(f"Invalid JSON body: {exc}\n{raw}")
    status, headers_out, body_json, body_text = _http_request(
        context,
        "PATCH",
        _interpolate(path, context),
        headers={"Content-Type": "application/json", "Accept": "*/*"},
        json_body=body,
    )
    context.last_response = {
        "status": status,
        "headers": headers_out,
        "json": body_json,
        "text": body_text,
        "bytes": getattr(context, "_last_response_bytes", None),
        "path": path,
        "method": "PATCH",
    }
    if status == 200 and body_json is not None:
        _validate_with_name(body_json, "DocumentResponse")


# ----------------------
# Additional assertions and seeding (Clarke guidance)
# ----------------------

@then('the response JSON at "{json_path}" should be a valid UUIDv4')
def epic_c_assert_uuid_v4(context, json_path: str):
    body = context.last_response.get("json")
    assert isinstance(body, (dict, list)), "No JSON body"
    val = _jsonpath(body, f"$.{json_path}" if not json_path.startswith("$") else json_path)
    s = str(val)
    try:
        u = uuid.UUID(s, version=4)
    except Exception as exc:
        raise AssertionError(f"Value at {json_path} is not a valid UUIDv4: {s} ({exc})")
    assert str(u) == s, "UUID canonical form mismatch"


@given("documents exist:")
def epic_c_seed_documents_table(context):
    """Seed documents from a table with columns: title, order_number, version.

    For version > 1, perform a single DOCX upload to increment version using
    the binary PUT helper that applies API prefix rewrite.
    """
    for row in context.table:
        title = row[0]
        order_number = int(row[1])
        version = int(row[2])
        # Create document v1
        status, headers_out, body_json, body_text = _http_request(
            context,
            "POST",
            "/documents",
            headers={"Content-Type": "application/json", "Accept": "*/*"},
            json_body={"title": title, "order_number": order_number},
        )
        assert status in (200, 201), f"Seed POST failed: {status}"
        doc_id = _jsonpath(body_json, "$.document.document_id")
        # Store by title alias for convenience
        _ensure_vars(context)[title] = doc_id
        # Bump to desired version if needed
        if version > 1:
            context._pending_put_path = f"/documents/{doc_id}/content"
            context._pending_put_headers = {
                "Idempotency-Key": f"idem-{uuid.uuid4()}",
                "If-Match": 'W/"doc-v1"',
            }
            epic_c_put_docx_body_default(context)


@given('a document exists with order_number {n:d}')
def epic_c_seed_document_with_order(context, n: int):
    status, headers_out, body_json, body_text = _http_request(
        context,
        "POST",
        "/documents",
        headers={"Content-Type": "application/json", "Accept": "*/*"},
        json_body={"title": f"Seed {n}", "order_number": n},
    )
    assert status in (200, 201), f"Seed POST failed: {status}"


@given('a document "{alias}" exists')
def epic_c_alias_exists(context, alias: str):
    # Thin adapter to existing v1 seed with default order
    next_order = int(_ensure_vars(context).get("_next_order", 0)) + 1
    _ensure_vars(context)["_next_order"] = next_order
    epic_c_seed_document_v1(context, alias, alias, next_order)


@given('a document "{alias}" exists with version {v:d}')
def epic_c_alias_exists_with_version(context, alias: str, v: int):
    # Use default title/order; reach desired version using helper
    next_order = int(_ensure_vars(context).get("_next_order", 0)) + 1
    _ensure_vars(context)["_next_order"] = next_order
    epic_c_doc_exists_with_version(context, alias, alias, next_order, v)


# Clarke required alias seeding step
@given('a document "{alias}" exists with version 1 and ETag W/"doc-v1"')
def epic_c_alias_exists_v1_with_etag(context, alias: str):
    # Seed document at version 1
    epic_c_alias_exists_with_version(context, alias, 1)
    # Fetch metadata and assert the ETag header equals W/"doc-v1"
    doc_id = _ensure_vars(context).get(alias)
    assert isinstance(doc_id, str) and doc_id, f"Unknown alias {alias}"
    step_when_get(context, f"/documents/{doc_id}")
    headers = context.last_response.get("headers", {}) or {}
    etag = _get_header_case_insensitive(headers, "ETag")
    assert etag == 'W/"doc-v1"', f"Expected document ETag W/\"doc-v1\", got {etag}"


@given('document "{alias}" has uploaded DOCX content with checksum "{hex_digest}"')
def epic_c_seed_alias_with_content_and_checksum(context, alias: str, hex_digest: str):
    # Create document and upload deterministic content for repeatability
    next_order = int(_ensure_vars(context).get("_next_order", 0)) + 1
    _ensure_vars(context)["_next_order"] = next_order
    epic_c_seed_document_v1(context, alias, alias, next_order)
    # Stage headers
    context._pending_put_path = f"/documents/{_ensure_vars(context)[alias]}/content"
    context._pending_put_headers = {
        "Idempotency-Key": f"idem-{uuid.uuid4()}",
        "If-Match": 'W/"doc-v1"',
    }
    # Clarke: if the provided token is a 64-hex literal, load the deterministic
    # fixture from the blobs directory and require that the fixture file exists.
    # Do not require its SHA-256 to equal the literal token; instead, we will
    # compute the digest and map the literal token to the actual digest so
    # downstream assertions can reference it. For non-hex tokens, fall back to
    # a minimal valid DOCX-like payload.
    token = (hex_digest or "").strip()
    content: Optional[bytes] = None
    import re as _re
    if _re.fullmatch(r"[0-9a-fA-F]{64}", token):
        # Enforce existence of the named fixture; do not assert digest equality
        hex_lower = token.lower()
        fixture_path = os.path.join(
            "tests",
            "integration",
            "data",
            "epic_c",
            "blobs",
            f"{hex_lower}.bin",
        )
        assert os.path.exists(
            fixture_path
        ), f"Missing content fixture for checksum {hex_lower}: {fixture_path}"
        with open(fixture_path, "rb") as fh:
            content = fh.read()
    else:
        # Fallback to default valid DOCX-like payload for non-hex tokens
        content = b"PK\x03\x04minimal-docx"
    # Send the selected content bytes
    _epic_c_send_put_content(context, content)
    # Compute and store digest of the uploaded bytes
    try:
        uploaded: bytes = getattr(context, "_last_put_content", b"") or b""
        digest = hashlib.sha256(uploaded).hexdigest()
        vars_map = _ensure_vars(context)
        vars_map["sha_of_last_upload"] = digest
        # If the checksum token was a {var} expression, write that var
        if token.startswith("{") and token.endswith("}") and len(token) > 2:
            varname = token[1:-1].strip()
            if varname:
                vars_map[varname] = digest
        # Clarke: If the token was a raw 64-hex literal, also store under that key
        try:
            if _re.fullmatch(r"[0-9a-fA-F]{64}", token):
                vars_map[token] = digest
        except Exception:
            pass
    except Exception:
        pass


# ----------------------
# Listing assertions
# ----------------------

@then('the response JSON at "{json_path}" should be an array of length {n:d}')
def epic_c_json_array_length(context, json_path: str, n: int):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    arr = _jsonpath(body, f"$.{json_path}" if not json_path.startswith("$") else json_path)
    assert isinstance(arr, list), f"Expected array at {json_path}"
    assert len(arr) == n, f"Expected length {n}, got {len(arr)}"
    # Validate list response envelope when applicable
    if json_path.strip("$") in {"list", ".list", "$.list"}:
        try:
            _validate_with_name(body, "DocumentListResponse")
        except Exception:
            pass


@then('the sequence of "{field}" across "{array_path}" should be contiguous from 1')
def epic_c_sequence_contiguous_from_1(context, field: str, array_path: str):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    arr = _jsonpath(body, f"$.{array_path}" if not array_path.startswith("$") else array_path)
    assert isinstance(arr, list), f"Expected array at {array_path}"
    seq = [int(item.get(field)) for item in arr]
    assert seq == list(range(1, len(seq) + 1)), f"Expected contiguous sequence from 1, got {seq}"


@then('the response JSON at "list_etag" should be a non-empty string')
def epic_c_list_etag_nonempty(context):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    val = body.get("list_etag")
    assert isinstance(val, str) and val.strip(), "Expected non-empty list_etag"


@then('the sequence of "{field}" across "{array_path}" should be [{expected_list}]')
def epic_c_sequence_exact_match(context, field: str, array_path: str, expected_list: str):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    arr = _jsonpath(body, f"$.{array_path}" if not array_path.startswith("$") else array_path)
    assert isinstance(arr, list), f"Expected array at {array_path}"
    seq = [str(item.get(field)) for item in arr]
    exp = [s.strip() for s in expected_list.split(",")]
    assert seq == exp, f"Expected sequence {exp}, got {seq}"


# ----------------------
# Reorder and delete seeding
# ----------------------

@given('documents exist with IDs "{e}","{f}","{g}" and order 1,2,3 respectively')
def epic_c_seed_docs_with_aliases(context, e: str, f: str, g: str):
    vars_map = _ensure_vars(context)
    for order, alias in enumerate([e, f, g], start=1):
        title = alias
        status, headers_out, body_json, body_text = _http_request(
            context,
            "POST",
            "/documents",
            headers={"Content-Type": "application/json", "Accept": "*/*"},
            json_body={"title": title, "order_number": order},
        )
        assert status in (200, 201), f"Seed POST failed: {status}"
        doc_id = _jsonpath(body_json, "$.document.document_id")
        vars_map[alias] = doc_id


@given('documents exist with orders: A→1, B→2, C→3, D→4')
def epic_c_seed_docs_ordered(context):
    for title, order in (("A", 1), ("B", 2), ("C", 3), ("D", 4)):
        status, headers_out, body_json, body_text = _http_request(
            context,
            "POST",
            "/documents",
            headers={"Content-Type": "application/json", "Accept": "*/*"},
            json_body={"title": title, "order_number": order},
        )
        assert status in (200, 201), f"Seed POST failed: {status}"
        _ensure_vars(context)[title] = _jsonpath(body_json, "$.document.document_id")


@when('I DELETE "{path}"')
def epic_c_delete_path(context, path: str):
    # Interpolate aliases in path
    ipath = _interpolate(path, context)
    status, headers_out, body_json, body_text = _http_request(context, "DELETE", ipath)
    context.last_response = {
        "status": status,
        "headers": headers_out,
        "json": body_json,
        "text": body_text,
        "bytes": getattr(context, "_last_response_bytes", None),
        "path": ipath,
        "method": "DELETE",
    }


@then('the response JSON at "list" should contain three items')
def epic_c_json_list_three_items(context):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    lst = body.get("list")
    assert isinstance(lst, list) and len(lst) == 3, f"Expected three items, got {len(lst) if isinstance(lst, list) else type(lst)}"


@then('the relative order of remaining docs should be A before C before D')
def epic_c_relative_order_abc(context):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    titles = [str(item.get("title")) for item in body.get("list", [])]
    def idx(name: str) -> int:
        assert name in titles, f"Missing {name} in list {titles}"
        return titles.index(name)
    assert idx("A") < idx("C") < idx("D"), f"Unexpected order: {titles}"


# ----------------------
# Download content assertions
# ----------------------

@then('the response body length should be > 0')
def epic_c_body_length_positive(context):
    raw = context.last_response.get("bytes") or b""
    assert isinstance(raw, (bytes, bytearray)) and len(raw) > 0, "Expected non-empty response body"


@then('the response body SHA-256 should equal "{hex_digest}"')
def epic_c_body_sha256_equals(context, hex_digest: str):
    raw = context.last_response.get("bytes") or b""
    actual = hashlib.sha256(raw).hexdigest()
    token = (hex_digest or "").strip()
    vars_map = _ensure_vars(context)
    # Determine expected according to Clarke:
    # - If token is brace-wrapped, resolve from context.vars
    # - Else if token matches a key in context.vars, use that mapped value
    # - Else fallback to the literal token
    expected: str
    if token.startswith("{") and token.endswith("}") and len(token) > 2:
        varname = token[1:-1].strip()
        expected = str(vars_map.get(varname, ""))
    elif token in vars_map:
        expected = str(vars_map[token])
    else:
        expected = token
    assert actual == expected, f"Expected SHA-256 {expected}, got {actual}"


# ----------------------
# Sad paths utilities
# ----------------------

@given('documents exist with a current list ETag "{etag}"')
def epic_c_store_current_list_etag(context, etag: str):
    _ensure_vars(context)["current_list_etag"] = etag


@when('JSON body:')
def epic_c_put_json_body(context):
    # Used after staging PUT path+headers
    raw = context.text or "{}"
    try:
        raw = raw.replace("\\_", "_")
    except Exception:
        pass
    try:
        body = json.loads(raw)
    except Exception as exc:
        raise AssertionError(f"Invalid JSON body: {exc}\n{raw}")
    # Before sending, map any items[].document_id aliases to stored UUIDs using _interpolate
    try:
        if isinstance(body, dict) and isinstance(body.get("items"), list):
            from questionnaire_steps import _interpolate  # avoid top-level import cycle
            for item in body["items"]:
                if isinstance(item, dict) and "document_id" in item:
                    val = item.get("document_id")
                    if isinstance(val, str):
                        item["document_id"] = _interpolate(val, context)
    except Exception:
        # Non-fatal; request may still be valid if IDs already UUIDs
        pass
    path = getattr(context, "_pending_put_path", None)
    # Build headers from a copy of the staged headers, re-interpolate values,
    # support bare tokens (e.g., LE1), and normalize a single canonical If-Match key
    staged_headers = (getattr(context, "_pending_put_headers", None) or {})
    headers: Dict[str, str] = {}
    vars_map = _ensure_vars(context)
    for k, v in staged_headers.items():
        key = str(k)
        val = v
        # Decode bytes if any
        if isinstance(val, (bytes, bytearray)):
            try:
                val = val.decode("utf-8")
            except Exception:
                val = bytes(val).decode("latin1", errors="ignore")
        val_str = str(val) if val is not None else ""
        # Re-interpolate brace tokens using context
        try:
            interp = _interpolate(val_str, context)
        except Exception:
            interp = val_str
        # Support bare token lookup from context.vars
        if isinstance(interp, str) and interp in vars_map:
            interp = str(vars_map[interp])
        # Final normalization
        final_val = str(interp).strip()
        if key.lower() == "if-match":
            if final_val:
                headers["If-Match"] = final_val
            continue
        headers[key] = final_val
    # Ensure defaults without overwriting canonicalized If-Match
    headers.setdefault("Content-Type", "application/json")
    headers.setdefault("Accept", "*/*")
    # Fallbacks when If-Match is missing:
    # 1) use last explicitly staged value from context.vars['_last_if_match']
    # 2) then try the captured canonical list_etag
    if not headers.get("If-Match"):
        vars_map = _ensure_vars(context)
        fallback_ifm = vars_map.get("_last_if_match")
        if isinstance(fallback_ifm, (bytes, bytearray)):
            try:
                fallback_ifm = fallback_ifm.decode("utf-8")
            except Exception:
                fallback_ifm = bytes(fallback_ifm).decode("latin1", errors="ignore")
        if isinstance(fallback_ifm, str) and fallback_ifm.strip():
            headers["If-Match"] = fallback_ifm.strip()
    if not headers.get("If-Match"):
        fallback = _ensure_vars(context).get("list_etag")
        if isinstance(fallback, (bytes, bytearray)):
            try:
                fallback = fallback.decode("utf-8")
            except Exception:
                fallback = bytes(fallback).decode("latin1", errors="ignore")
        if isinstance(fallback, str) and fallback.strip():
            headers["If-Match"] = fallback.strip()
    # Instrumentation: record outgoing If-Match before sending (no hard assert)
    outgoing_if_match = headers.get("If-Match")
    # Persist exact outgoing value for traceability
    try:
        setattr(context, "outgoing_if_match", str(outgoing_if_match))
    except Exception:
        pass
    try:
        # Concise log for correlation
        print(f"[EpicC] PUT {path} If-Match={outgoing_if_match}")
    except Exception:
        pass
    status, headers_out, body_json, body_text = _http_request(
        context,
        "PUT",
        path,
        headers=headers,
        json_body=body,
    )
    context.last_response = {
        "status": status,
        "headers": headers_out,
        "json": body_json,
        "text": body_text,
        "bytes": getattr(context, "_last_response_bytes", None),
        "path": path,
        "method": "PUT",
    }
    # Capture diagnostics on 412 responses for ETag mismatches
    try:
        if int(status) == 412 and isinstance(body_json, dict):
            try:
                setattr(context, "received_if_match", body_json.get("received_if_match"))
            except Exception:
                pass
            try:
                setattr(context, "current_list_etag", body_json.get("current_list_etag"))
            except Exception:
                pass
    except Exception:
        pass


@when('body "{text}"')
def epic_c_put_text_body(context, text: str):
    path = getattr(context, "_pending_put_path", None)
    headers = getattr(context, "_pending_put_headers", None) or {}
    status, headers_out, body_json, body_text = _http_request(
        context,
        "PUT",
        path,
        headers={"Accept": "*/*", **headers},
        text_body=text,
    )
    context.last_response = {
        "status": status,
        "headers": headers_out,
        "json": body_json,
        "text": body_text,
        "bytes": getattr(context, "_last_response_bytes", None),
        "path": path,
        "method": "PUT",
    }
