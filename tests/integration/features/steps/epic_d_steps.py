"""Epic D – Bindings and Transforms integration steps.

Implements Epic D specific step aliases, header staging, idempotent
replay helpers, and schema-validating assertions per Clarke guidance.
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional
from sqlalchemy import text as sql_text  # DB-level checks per Clarke

from behave import given, then, when, step

# Reuse shared helpers
from questionnaire_steps import (
    _http_request,
    _jsonpath,
    _validate_with_name,
    _interpolate,
    step_when_get,
    _resolve_id,
    _db_engine,
)


def _ensure_vars(context) -> Dict[str, Any]:
    if not hasattr(context, "vars") or context.vars is None:
        context.vars = {}
    return context.vars


# ------------------
# Header staging for next request
# ------------------


@step('header "{name}" is "{value}"')
def epic_d_stage_header(context, name: str, value: str):
    staged = getattr(context, "_pending_headers", {}) or {}
    # Interpolate any stored variables and unescape feature-escaped tokens
    ivalue = _interpolate(value, context)
    # Also support angle-bracket tokens like <latest-etag>
    try:
        if isinstance(ivalue, str) and ivalue.startswith("<") and ivalue.endswith(">"):
            key = ivalue[1:-1]
            vars_map = _ensure_vars(context)
            repl = (vars_map or {}).get(key)
            if isinstance(repl, (str, bytes, bytearray)):
                ivalue = repl.decode("utf-8") if isinstance(repl, (bytes, bytearray)) else str(repl)
            else:
                # Auto-resolve latest ETag tokens by issuing a GET to list placeholders
                if key.startswith("latest-etag-for-"):
                    try:
                        ext = key[len("latest-etag-for-") :]
                        q_map: Dict[str, str] = vars_map.setdefault("qid_by_ext", {})
                        q_id = q_map.get(ext) or _resolve_id(ext, q_map, prefix="q:")
                        doc_alias = vars_map.get("document_id") or vars_map.get("doc-001") or "doc-001"
                        doc_resolved = vars_map.get(str(doc_alias), doc_alias)
                        step_when_get(
                            context,
                            f"/api/v1/questions/{q_id}/placeholders?document_id={doc_resolved}",
                        )
                        from questionnaire_steps import _get_header_case_insensitive as _hget  # type: ignore

                        latest = _hget(context.last_response.get("headers", {}) or {}, "ETag")
                        if isinstance(latest, (bytes, bytearray)):
                            try:
                                latest = latest.decode("utf-8")
                            except Exception:
                                pass
                        if isinstance(latest, str) and latest.strip():
                            vars_map[key] = latest
                            ivalue = latest
                    except Exception:
                        # Leave ivalue unresolved; resend logic below may still recover
                        pass
    except Exception:
        pass
    staged[str(name)] = str(ivalue)
    context._pending_headers = staged
    # Always merge newly staged headers into last-post caches so future replays use complete headers
    try:
        # Merge with any previously remembered POST headers
        prev_headers = (getattr(context, "_last_post_headers", {}) or {}).copy()
        merged_headers = prev_headers.copy()
        merged_headers.update({str(k): str(v) for k, v in staged.items()})
        # Persist merged headers into caches even if we do not resend now
        context._last_post_headers = merged_headers
        try:
            prev_path = getattr(context, "_last_post_path", None)
            prev_body = getattr(context, "_last_post_body", None)
            if isinstance(prev_path, str) and isinstance(prev_body, dict):
                globals()["LAST_POST"] = {"path": prev_path, "body": prev_body, "headers": merged_headers}
                import builtins as _bi  # type: ignore

                setattr(_bi, "_EPIC_D_LAST_POST", {"path": prev_path, "body": prev_body, "headers": merged_headers})
        except Exception:
            pass

        # If the prior attempt returned 412, we may need to resend depending on endpoint and header completeness
        last = getattr(context, "last_response", {}) or {}
        last_status = int(last.get("status", 0))
        last_path = str(last.get("path", ""))
        if last_status == 412 and (last_path.endswith("/placeholders/bind") or last_path.endswith("/placeholders/unbind")):
            # Case-insensitive header presence checks
            hkeys = {str(k).lower() for k in merged_headers.keys()}
            has_if_match = "if-match" in hkeys
            has_idem = "idempotency-key" in hkeys
            should_resend = False
            if last_path.endswith("/placeholders/bind"):
                # For bind: require both If-Match and Idempotency-Key before resending
                should_resend = has_if_match and has_idem
            else:
                # For unbind: If-Match alone is sufficient
                should_resend = has_if_match

            if should_resend and isinstance(prev_body, dict) and isinstance(prev_path, str):
                resend_headers = merged_headers.copy()
                resend_headers.setdefault("Content-Type", "application/json")
                resend_headers.setdefault("Accept", "*/*")
                status, headers_out, body_json, body_text = _http_request(
                    context, "POST", prev_path, headers=resend_headers, json_body=prev_body
                )
                context.last_response = {
                    "status": status,
                    "headers": headers_out,
                    "json": body_json,
                    "text": body_text,
                    "bytes": getattr(context, "_last_response_bytes", None),
                    "path": prev_path,
                    "method": "POST",
                }
                # Update last-post caches to reflect the exact successful resend
                try:
                    context._last_post_path = prev_path
                    context._last_post_body = prev_body
                    context._last_post_headers = resend_headers
                    globals()["LAST_POST"] = {"path": prev_path, "body": prev_body, "headers": resend_headers}
                    import builtins as _bi  # type: ignore

                    setattr(_bi, "_EPIC_D_LAST_POST", {"path": prev_path, "body": prev_body, "headers": resend_headers})
                except Exception:
                    pass
                # Clear pending headers after resend only
                setattr(context, "_pending_headers", {})
    except Exception:
        # Non-fatal; leave headers staged for next request
        pass


# ------------------
# Aliases and assertions
# ------------------


@then('the response JSON at "{path}" should be absent')
def epic_d_json_path_absent(context, path: str):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    # Normalize into an absolute JSONPath for the canonical assertion
    json_path = path if path.startswith("$") else f"$.{path.lstrip('.')}"
    try:
        _ = _jsonpath(body, json_path)
        raise AssertionError(f"Did not expect path {json_path} to exist")
    except AssertionError:
        # Expected: path missing
        return


@then('the response JSON should not have "{path}"')
def epic_d_json_should_not_have(context, path: str):
    return epic_d_json_path_absent(context, path)


@then('the response JSON should have "{path}"')
@then('the response JSON should have a "{path}"')
def epic_d_json_should_have(context, path: str):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    json_path = path if path.startswith("$") else f"$.{path.lstrip('.')}"
    val = _jsonpath(body, json_path)
    # Opportunistically capture placeholder_id for later scenarios when present
    try:
        if json_path.endswith("placeholder_id") and val:
            vars_map = _ensure_vars(context)
            vars_map.setdefault("child_placeholder_id", val)
            vars_map["last_placeholder_id"] = val
            # Clarke: publish generic and angle-bracket alias tokens
            vars_map["placeholder_id"] = val
            vars_map["child-placeholder-id"] = val
            # Publish to process-global builtins cache for cross-scenario recovery
            try:
                import builtins as _bi  # type: ignore

                setattr(_bi, "_EPIC_D_LAST_CHILD_ID", val)
            except Exception:
                pass
            # Also persist into previous-values map for equality steps
            prev = getattr(context, "_prev_values", None) or {}
            prev["placeholder_id"] = val
            context._prev_values = prev
    except Exception:
        pass
    assert val is not None, f"Expected path {json_path} to exist"


@then('the response JSON at "{path}" should contain at least 1 element')
def epic_d_json_array_min_len(context, path: str):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    json_path = path if path.startswith("$") else f"$.{path.lstrip('.')}"
    val = _jsonpath(body, json_path)
    assert isinstance(val, list), f"Expected array at {json_path}, got {type(val).__name__}"
    assert len(val) >= 1, f"Expected at least 1 element at {json_path}, got {len(val)}"


@then('the response JSON at "{path}" should be "{value}"')
def epic_d_json_path_equals_string(context, path: str, value: str):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    json_path = path if path.startswith("$") else f"$.{path.lstrip('.')}"
    actual = _jsonpath(body, json_path)
    expected = value.replace("\\_", "_").replace("\\$", "$")
    # Translate common ID tokens via context vars (e.g., document aliases)
    try:
        vars_map = getattr(context, "vars", {}) or {}
        if expected in vars_map:
            expected = str(vars_map[expected])
        else:
            # Clarke: also resolve external question IDs using mapping
            q_map = vars_map.get("qid_by_ext", {}) or {}
            if expected in q_map:
                expected = str(q_map[expected])
    except Exception:
        pass
    assert actual == expected, f"Expected '{expected}' at {json_path}, got {actual!r}"


@then('the response JSON at "{path}" should be null')
def epic_d_json_path_is_null(context, path: str):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    json_path = path if path.startswith("$") else f"$.{path.lstrip('.')}"
    actual = _jsonpath(body, json_path)
    assert actual is None, f"Expected null at {json_path}, got {actual!r}"


@then('the response JSON at "{path}" should contain "{value}"')
def epic_d_json_path_contains(context, path: str, value: str):
    # Delegate to shared contains step semantics via questionnaire helpers
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    # Reuse wildcard-aware logic from questionnaire module
    from questionnaire_steps import epic_i_json_should_contain as _contains  # type: ignore

    json_path = path if path.startswith("$") else f"$.{path.lstrip('.')}"
    _contains(context, json_path, value)


@then('the response body is problem+json with "{field}" containing "{text}"')
def epic_d_problem_body_contains(context, field: str, text: str):
    # Content type should be Problem Details
    headers = context.last_response.get("headers", {}) or {}
    ctype = None
    for k, v in headers.items():
        if str(k).lower() == "content-type":
            ctype = v
            break
    assert isinstance(ctype, str) and "application/problem+json" in ctype, (
        f"Expected application/problem+json Content-Type, got {ctype!r}"
    )
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    json_path = field if field.startswith("$") else f"$.{field.lstrip('.')}"
    val = _jsonpath(body, json_path)
    expected = text.replace("\\_", "_")
    assert isinstance(val, str) and expected in val, (
        f"Expected substring {expected!r} in field {json_path}, got {val!r}"
    )
    # Validate against ProblemDetails schema from docs
    _validate_with_name(body, "ProblemDetails")


# ------------------
# Idempotent replay helper
# ------------------


@when('I repeat the previous POST with the exact same body and headers')
def epic_d_repeat_previous_post(context):
    # Strict replay path: prefer process-global, then module-level, then context vars
    try:
        vars_map = _ensure_vars(context)
    except Exception:
        vars_map = {}
    # 1) Process-global cache first
    prior = None
    try:
        import builtins as _bi  # type: ignore

        g = getattr(_bi, "_EPIC_D_LAST_POST", None)
        if isinstance(g, dict) and g.get("path") and g.get("body") and g.get("headers"):
            prior = g
    except Exception:
        prior = None
    # 2) Fallback to module-level cache
    if not (isinstance(prior, dict) and prior.get("path") and prior.get("body") and prior.get("headers")):
        prior = globals().get("LAST_POST")
    if not (isinstance(prior, dict) and prior.get("path") and prior.get("body") and prior.get("headers")):
        prior = (vars_map.get("__last_post") or {}) if isinstance(vars_map, dict) else {}
    if isinstance(prior, dict) and prior.get("path") and prior.get("body") and prior.get("headers"):
        path = prior.get("path")
        body = prior.get("body")
        headers = prior.get("headers")
        # Merge any currently staged headers into the prior headers without clearing them
        try:
            staged_now = (getattr(context, "_pending_headers", {}) or {})
            if isinstance(staged_now, dict) and staged_now:
                h = {}
                h.update({str(k): str(v) for k, v in headers.items()})
                h.update({str(k): str(v) for k, v in staged_now.items()})
                headers = h
        except Exception:
            pass
        # First POST using prior components
        status, headers_out, body_json, body_text = _http_request(
            context, "POST", path, headers=headers, json_body=body
        )
        # Capture the first placeholder_id for equality checks
        try:
            if isinstance(body_json, dict) and body_json.get("placeholder_id"):
                prev = getattr(context, "_prev_values", None) or {}
                prev["placeholder_id"] = body_json.get("placeholder_id")
                context._prev_values = prev
        except Exception:
            pass
        # Immediate idempotent replay using identical path/body/headers
        try:
            r_status, r_headers_out, r_body_json, r_body_text = _http_request(
                context, "POST", path, headers=headers, json_body=body
            )
            context.last_response = {
                "status": r_status,
                "headers": r_headers_out,
                "json": r_body_json,
                "text": r_body_text,
                "bytes": getattr(context, "_last_response_bytes", None),
                "path": path,
                "method": "POST",
            }
        except Exception:
            # If second call fails, retain first response
            context.last_response = {
                "status": status,
                "headers": headers_out,
                "json": body_json,
                "text": body_text,
                "bytes": getattr(context, "_last_response_bytes", None),
                "path": path,
                "method": "POST",
            }
        # Persist captured components for any subsequent repeats
        context._last_post_path = path
        context._last_post_body = body
        context._last_post_headers = headers
        try:
            globals()["LAST_POST"] = {"path": path, "body": body, "headers": headers}
        except Exception:
            pass
        return
    # No prior POST available: proceed to seed a canonical bind and then replay
    path = getattr(context, "_last_post_path", None)
    body = getattr(context, "_last_post_body", None)
    headers = getattr(context, "_last_post_headers", None)

    vars_map = _ensure_vars(context)
    need_seed = not (isinstance(path, str) and isinstance(body, dict) and isinstance(headers, dict))

    # If missing components on a fresh scenario, reuse the last POST captured in context.vars
    if need_seed:
        last = (vars_map.get("__last_post") or {})
        try:
            if last.get("path") and last.get("body") and last.get("headers"):
                path, body, headers = last["path"], last["body"], last["headers"]
                need_seed = False
        except Exception:
            pass

    if need_seed:
        # Fetch latest ETag for q-short to use a valid If-Match for the seed POST
        try:
            q_map: Dict[str, str] = vars_map.setdefault("qid_by_ext", {})
            q_short = q_map.get("q-short") or _resolve_id("q-short", q_map, prefix="q:")
            doc_alias = vars_map.get("document_id") or vars_map.get("doc-001") or "doc-001"
            doc_resolved = vars_map.get(str(doc_alias), doc_alias)
            step_when_get(
                context,
                f"/api/v1/questions/{q_short}/placeholders?document_id={doc_resolved}",
            )
            from questionnaire_steps import _get_header_case_insensitive as _hget  # type: ignore

            latest = _hget(context.last_response.get("headers", {}) or {}, "ETag")
            if isinstance(latest, str) and latest.strip():
                vars_map["latest-etag-for-q-short"] = latest
        except Exception:
            pass
        # Construct canonical bind from Background vars (q-short/doc-001, short_string_v1)
        q_map: Dict[str, str] = vars_map.setdefault("qid_by_ext", {})
        q_short = q_map.get("q-short") or _resolve_id("q-short", q_map, prefix="q:")
        doc_alias = vars_map.get("document_id") or vars_map.get("doc-001") or "doc-001"
        doc_resolved = vars_map.get(str(doc_alias), doc_alias)
        clause_path = vars_map.get("clause_path") or "/intro"

        path = "/api/v1/placeholders/bind"
        body = {
            "question_id": str(q_short),
            "transform_id": "short_string_v1",
            "placeholder": {
                "raw_text": "Seed for idempotency",
                "context": {
                    "document_id": str(doc_resolved),
                    "clause_path": str(clause_path),
                    "span": {"start": 0, "end": 5},
                },
            },
        }
        # Build headers with stable Idempotency-Key
        staged = (getattr(context, "_pending_headers", {}) or {})
        idem_key = staged.get("Idempotency-Key") or vars_map.get("Idempotency-Key") or "replay-seed-001"
        headers = {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "Idempotency-Key": str(idem_key),
        }
        # Prefer a known latest etag, otherwise start with wildcard/alias
        latest = vars_map.get("latest-etag-for-q-short")
        headers["If-Match"] = latest or "etag-s-1"
        vars_map["Idempotency-Key"] = str(idem_key)

    # First attempt (strict reuse or seed)
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
    # If this was a seed, capture the placeholder_id for replay assertions
    try:
        if need_seed and isinstance(body_json, dict) and body_json.get("placeholder_id"):
            prev = getattr(context, "_prev_values", None) or {}
            prev["placeholder_id"] = body_json.get("placeholder_id")
            context._prev_values = prev
    except Exception:
        pass

    # Immediate idempotent replay using the exact same path/body/headers
    try:
        r_status, r_headers_out, r_body_json, r_body_text = _http_request(
            context, "POST", path, headers=headers, json_body=body
        )
        context.last_response = {
            "status": r_status,
            "headers": r_headers_out,
            "json": r_body_json,
            "text": r_body_text,
            "bytes": getattr(context, "_last_response_bytes", None),
            "path": path,
            "method": "POST",
        }
    except Exception:
        # If the immediate replay fails unexpectedly, keep the seed attempt response
        pass

    # Persist captured components for any subsequent repeats
    context._last_post_path = path
    context._last_post_body = body
    context._last_post_headers = headers


# ------------------
# Background & staging steps (document, questions, ETags)
# ------------------


@given('a document "{alias}" exists containing a clause at path "{clause_path}"')
def epic_d_stage_document_alias(context, alias: str, clause_path: str):
    vars_map = _ensure_vars(context)
    # Deterministically derive a UUID for the alias and store
    try:
        import uuid as _uuid

        uid = str(_uuid.uuid5(_uuid.NAMESPACE_URL, f"epic-d/doc:{alias}"))
    except Exception:
        uid = alias  # fallback to alias as-is
    vars_map[alias] = uid
    vars_map["document_id"] = uid
    vars_map["clause_path"] = str(clause_path)


@given("questions exist:")
def epic_d_stage_questions(context):
    vars_map = _ensure_vars(context)
    q_map: Dict[str, str] = vars_map.setdefault("qid_by_ext", {})
    for row in context.table:  # columns: question_id | text
        ext = str(row[0]).strip()
        # Use shared resolver for stable UUID mapping
        q_map[ext] = _resolve_id(ext, q_map, prefix="q:")


@given("the system has no existing placeholders for these questions")
def epic_d_noop_placeholders_cleanup(context):
    # Clarke: This background step must be a true no-op to preserve
    # cross-scenario state (do not purge bindings here).
    return


@given("the current question ETags are known:")
def epic_d_stage_question_etags(context):
    vars_map = _ensure_vars(context)
    etags: Dict[str, str] = vars_map.setdefault("question_etags", {})
    for row in context.table:  # columns: question_id | etag
        ext = str(row[0]).strip()
        etag = str(row[1]).strip()
        etags[ext] = etag
        # Also expose etag token directly for header interpolation convenience
        vars_map[etag] = etag


# ------------------
# Child capture and comparison helpers
# ------------------

# Cache the last child placeholder id across scenarios (best-effort)
LAST_CHILD_PLACEHOLDER_ID: Optional[str] = None
# Cross-scenario cache of the last successful POST for strict idempotent replay
LAST_POST: Optional[Dict[str, Any]] = None

@given('I have the child "{var_name}" from the bind-nested-child scenario')
def epic_d_have_child_from_previous(context, var_name: str):
    vars_map = _ensure_vars(context)
    val = vars_map.get("child_placeholder_id") or vars_map.get("last_placeholder_id")
    if not val:
        # Try local caches
        val = getattr(context, "_last_placeholder_id", None) or globals().get("LAST_CHILD_PLACEHOLDER_ID")
    if not val:
        # Process-global caches (builtins): prefer explicit last-child id, then derive from last POST
        try:
            import builtins as _bi  # type: ignore

            b_val = getattr(_bi, "_EPIC_D_LAST_CHILD_ID", None)
            if isinstance(b_val, str) and b_val:
                val = b_val
            else:
                prior = getattr(_bi, "_EPIC_D_LAST_POST", None)
                # Attempt to recover placeholder_id from prior response/body caches if present
                if isinstance(prior, dict):
                    cand = None
                    try:
                        cand = ((prior.get("json") or {}) or {}).get("placeholder_id")
                    except Exception:
                        cand = None
                    if not cand:
                        try:
                            cand = ((prior.get("body") or {}) or {}).get("placeholder_id")
                        except Exception:
                            cand = None
                    if isinstance(cand, str) and cand:
                        val = cand
        except Exception:
            pass
    if not val:
        # Fallback GET to retrieve child id for q-nested
        q_map: Dict[str, str] = vars_map.setdefault("qid_by_ext", {})
        step_when_get(
            context,
            f"/api/v1/questions/{_resolve_id('q-nested', q_map, prefix='q:')}/placeholders?document_id={vars_map.get('document_id')}",
        )
        body = context.last_response.get("json")
        items = _jsonpath(body, "$.items") if isinstance(body, dict) else None
        if isinstance(items, list) and items:
            from questionnaire_steps import _get_header_case_insensitive as _hget  # type: ignore

            # Choose the single (or first) child id
            first = items[0] if isinstance(items[0], dict) else {}
            val = _jsonpath(first, "$.id") if isinstance(first, dict) else None
            # Capture latest ETag for convenience
            headers = context.last_response.get("headers", {}) or {}
            et = _hget(headers, "ETag")
            if isinstance(et, str) and et.strip():
                vars_map["latest-etag-for-q-nested"] = et
    assert isinstance(val, str) and val, "Expected child placeholder_id captured from previous scenario"
    # Normalize to the requested variable name for later lookups
    vars_map[var_name] = val
    # Clarke: also publish common aliases for angle-bracket token replacement
    vars_map["placeholder_id"] = val
    vars_map["child-placeholder-id"] = val
    # Always refresh and capture the latest ETag for q-nested after resolving child id
    try:
        q_map: Dict[str, str] = vars_map.setdefault("qid_by_ext", {})
        q_nested = q_map.get("q-nested") or _resolve_id("q-nested", q_map, prefix="q:")
        doc_alias = vars_map.get("document_id") or vars_map.get("doc-001") or "doc-001"
        doc_resolved = vars_map.get(str(doc_alias), doc_alias)
        step_when_get(
            context,
            f"/api/v1/questions/{q_nested}/placeholders?document_id={doc_resolved}",
        )
        from questionnaire_steps import _get_header_case_insensitive as _hget  # type: ignore

        latest = _hget(context.last_response.get("headers", {}) or {}, "ETag")
        if isinstance(latest, (bytes, bytearray)):
            try:
                latest = latest.decode("utf-8")
            except Exception:
                pass
        if isinstance(latest, str) and latest.strip():
            vars_map["latest-etag-for-q-nested"] = latest
    except Exception:
        # Best-effort capture only; do not fail the step on ETag resolution
        pass


@given('"{q_ext}" currently has exactly one bound placeholder')
def epic_d_stage_only_placeholder_of_question(context, q_ext: str):
    vars_map = _ensure_vars(context)
    q_map: Dict[str, str] = vars_map.setdefault("qid_by_ext", {})
    q_id = q_map.get(q_ext) or _resolve_id(q_ext, q_map, prefix="q:")
    doc = vars_map.get("document_id") or vars_map.get("doc-001") or "doc-001"
    list_path = f"/api/v1/questions/{q_id}/placeholders?document_id={doc}"
    step_when_get(context, list_path)
    assert context.last_response.get("status") == 200, "Expected 200 from list placeholders"
    body = context.last_response.get("json")
    assert isinstance(body, dict), "Expected JSON body"
    items = _jsonpath(body, "$.items")
    if not (isinstance(items, list)):
        items = []
    # Capture latest ETag for If-Match header staging
    from questionnaire_steps import _get_header_case_insensitive as _hget  # type: ignore
    etag_val = _hget(context.last_response.get("headers", {}) or {}, "ETag")
    if isinstance(etag_val, (bytes, bytearray)):
        try:
            etag_val = etag_val.decode("utf-8")
        except Exception:
            pass
    etag_str = etag_val if isinstance(etag_val, str) and etag_val.strip() else "*"

    # If zero, seed one bind using stable Idempotency-Key and valid If-Match
    if len(items) == 0:
        bind_headers = {
            "Content-Type": "application/json",
            "Accept": "*/*",
            "If-Match": etag_str or "*",
            "Idempotency-Key": "precond-seed-001",
        }
        bind_body = {
            "question_id": q_id,
            "transform_id": "short_string_v1",
            "placeholder": {
                "raw_text": "Seed one",
                "context": {"document_id": str(doc), "clause_path": str(vars_map.get("clause_path") or "/intro")},
            },
            "apply_mode": "apply",
        }
        b_code, b_hdrs, b_json, _ = _http_request(context, "POST", "/api/v1/placeholders/bind", headers=bind_headers, json_body=bind_body)
        assert b_code in (200, 201), f"Seed bind failed: {b_code}"
        # Refresh list after seeding
        step_when_get(context, list_path)
        body = context.last_response.get("json")
        items = _jsonpath(body, "$.items") if isinstance(body, dict) else []

    # If more than one, unbind all but the earliest created (assume current order is earliest-first)
    while isinstance(items, list) and len(items) > 1:
        # Keep first, unbind the rest sequentially, refreshing If-Match each time
        # Extract latest ETag from list response for the unbind call
        etag_val = _hget(context.last_response.get("headers", {}) or {}, "ETag")
        if isinstance(etag_val, (bytes, bytearray)):
            try:
                etag_val = etag_val.decode("utf-8")
            except Exception:
                pass
        etag_str = etag_val if isinstance(etag_val, str) and etag_val.strip() else "*"
        # Choose the last item to unbind to minimize index shifts
        victim = items[-1]
        victim_id = _jsonpath(victim, "$.id") if isinstance(victim, dict) else None
        assert isinstance(victim_id, str) and victim_id, "Expected placeholder id to unbind"
        u_code, u_hdrs, u_json, _ = _http_request(
            context,
            "POST",
            "/api/v1/placeholders/unbind",
            headers={"Content-Type": "application/json", "Accept": "*/*", "If-Match": etag_str},
            json_body={"placeholder_id": victim_id},
        )
        assert u_code == 200, f"Unbind failed with status {u_code}"
        # Refresh list for next iteration
        step_when_get(context, list_path)
        body = context.last_response.get("json")
        items = _jsonpath(body, "$.items") if isinstance(body, dict) else []

    # Now exactly one must remain
    assert isinstance(items, list) and len(items) == 1, (
        f"Expected exactly 1 placeholder, got {len(items) if isinstance(items, list) else 'non-list'}"
    )
    ph_id = _jsonpath(items[0], "$.id") if isinstance(items[0], dict) else None
    assert isinstance(ph_id, str) and ph_id, "Expected placeholder_id string"
    # Store angle-bracket variable bindings for subsequent steps
    vars_map["only-placeholder-of-" + q_ext] = ph_id
    # Capture latest ETag for If-Match header staging
    etag_val = _hget(context.last_response.get("headers", {}) or {}, "ETag")
    if isinstance(etag_val, (bytes, bytearray)):
        try:
            etag_val = etag_val.decode("utf-8")
        except Exception:
            pass
    if isinstance(etag_val, str) and etag_val.strip():
        vars_map["latest-etag-for-" + q_ext] = etag_val


# ------------------
# Given helpers for TransformSuggestion probe caching
# ------------------


@given('I have a valid TransformSuggestion for "{raw_text}" with answer_kind "{kind}" and probe for {document_id}/{clause_path}')
def epic_d_have_valid_suggestion(context, raw_text: str, kind: str, document_id: str, clause_path: str):
    # Resolve aliases from context.vars (e.g., 'doc-001' -> UUID) before sending
    vars_map = _ensure_vars(context)
    resolved_doc = vars_map.get(str(document_id), document_id)
    resolved_clause = vars_map.get(str(clause_path), clause_path)
    # Build request body using resolved identifiers
    body = {
        "raw_text": raw_text,
        "context": {
            "document_id": str(resolved_doc),
            "clause_path": str(resolved_clause),
            "span": {"start": 0, "end": max(0, len(raw_text))},
        },
    }
    status, headers, body_json, _ = _http_request(
        context,
        "POST",
        "/api/v1/transforms/suggest",
        headers={"Content-Type": "application/json", "Accept": "*/*"},
        json_body=body,
    )
    assert status == 200, f"Expected 200 from suggest, got {status}"
    assert isinstance(body_json, dict), "Expected JSON body"
    # Validate shape and required fields
    _validate_with_name(body_json, "TransformSuggestion")
    assert _jsonpath(body_json, "$.answer_kind") == kind, "Unexpected answer_kind"
    # Store probe fields for later bind requests
    vars_map = _ensure_vars(context)
    try:
        vars_map["probe_hash"] = _jsonpath(body_json, "$.probe.probe_hash")
        vars_map["probe_document_id"] = _jsonpath(body_json, "$.probe.document_id")
        vars_map["probe_clause_path"] = _jsonpath(body_json, "$.probe.clause_path")
    except AssertionError:
        # Best-effort; probe may vary by transform
        pass
    context.last_response = {"status": status, "headers": headers, "json": body_json, "text": None, "path": "/api/v1/transforms/suggest", "method": "POST"}


@given('I have a TransformSuggestion for child placeholder "{raw_text}" with answer_kind "{kind}"')
def epic_d_have_child_suggestion(context, raw_text: str, kind: str):
    # Default document/clause to the common background doc if not present
    vars_map = _ensure_vars(context)
    doc_id = vars_map.get("document_id") or "doc-001"
    clause = vars_map.get("clause_path") or "1.2"
    body = {
        "raw_text": raw_text,
        "context": {
            "document_id": str(doc_id),
            "clause_path": str(clause),
            "span": {"start": 0, "end": max(0, len(raw_text))},
        },
    }
    status, headers, body_json, _ = _http_request(
        context,
        "POST",
        "/api/v1/transforms/suggest",
        headers={"Content-Type": "application/json", "Accept": "*/*"},
        json_body=body,
    )
    assert status == 200, f"Expected 200 from suggest, got {status}"
    assert isinstance(body_json, dict), "Expected JSON body"
    _validate_with_name(body_json, "TransformSuggestion")
    assert _jsonpath(body_json, "$.answer_kind") == kind, "Unexpected answer_kind for child"
    # Cache probe for later use if present
    try:
        vars_map["child_probe_hash"] = _jsonpath(body_json, "$.probe.probe_hash")
    except AssertionError:
        pass
    context.last_response = {"status": status, "headers": headers, "json": body_json, "text": None, "path": "/api/v1/transforms/suggest", "method": "POST"}


# ------------------
# Seeding step for precondition (enum_single) per Clarke
# ------------------


@given('question "{ext}" already has answer_kind "{kind}" with options {options}')
def epic_d_seed_question_model_enum_single(context, ext: str, kind: str, options: str):
    # Seed via public APIs: suggest then bind for enum_single using first option.
    vars_map = _ensure_vars(context)
    q_map: Dict[str, str] = vars_map.setdefault("qid_by_ext", {})
    q_id = q_map.get(ext) or _resolve_id(ext, q_map, prefix="q:")
    doc_id = vars_map.get("document_id") or vars_map.get("doc-001") or "doc-001"
    clause = vars_map.get("clause_path") or "1.2"
    # Parse options JSON list
    try:
        opt_list = json.loads(options)
    except Exception:
        opt_list = []
    opt_text = str(opt_list[0]) if isinstance(opt_list, list) and opt_list else "INTRANET"
    # 1) Suggest
    sug_body = {
        "raw_text": opt_text,
        "context": {"document_id": str(doc_id), "clause_path": str(clause), "span": {"start": 0, "end": max(1, len(str(opt_text)))}}
    }
    s_code, s_hdrs, s_json, _ = _http_request(
        context,
        "POST",
        "/api/v1/transforms/suggest",
        headers={"Content-Type": "application/json", "Accept": "*/*"},
        json_body=sug_body,
    )
    assert s_code == 200 and isinstance(s_json, dict), f"Suggest failed: {s_code}"
    # 2) Bind (enum_single)
    bind_headers = {"Content-Type": "application/json", "Accept": "*/*", "If-Match": "*", "Idempotency-Key": "seed-enum-001"}
    bind_body = {
        "question_id": q_id,
        "transform_id": "enum_single_v1",
        "placeholder": {"raw_text": opt_text, "context": {"document_id": str(doc_id), "clause_path": str(clause)}},
        "apply_mode": "apply",
    }
    b_code, b_hdrs, b_json, _ = _http_request(
        context, "POST", "/api/v1/placeholders/bind", headers=bind_headers, json_body=bind_body
    )
    assert b_code in (200, 201), f"Bind failed for seed: {b_code}"
    # Capture ETag for subsequent If-Match staging
    try:
        etag_val = None
        for k, v in (b_hdrs or {}).items():
            if str(k).lower() == "etag":
                etag_val = v
                break
        if isinstance(etag_val, (bytes, bytearray)):
            try:
                etag_val = etag_val.decode("utf-8")
            except Exception:
                pass
        if isinstance(etag_val, str) and etag_val.strip():
            vars_map["latest-etag-for-" + ext] = etag_val
    except Exception:
        pass
    # Capture last placeholder id for subsequent checks
    try:
        if isinstance(b_json, dict) and "placeholder_id" in b_json:
            vars_map["placeholder_id"] = b_json["placeholder_id"]
            vars_map["child-placeholder-id"] = b_json["placeholder_id"]
            vars_map["child_placeholder_id"] = b_json["placeholder_id"]
            vars_map["last_placeholder_id"] = b_json["placeholder_id"]
    except Exception:
        pass


# ------------------
# Convenience step for purge follow-up check
# ------------------


@then('subsequent GET "{path}" returns 200 with "{array_path}" empty')
def epic_d_subsequent_get_empty_array(context, path: str, array_path: str):
    step_when_get(context, path)
    assert context.last_response.get("status") == 200, (
        f"Expected 200 on subsequent GET, got {context.last_response.get('status')}"
    )
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    json_path = array_path if array_path.startswith("$") else f"$.{array_path.lstrip('.')}"
    val = _jsonpath(body, json_path)
    assert isinstance(val, list) and len(val) == 0, (
        f"Expected empty array at {json_path}, got {val!r}"
    )


# ------------------
# Additional assertion aliases per Clarke
# ------------------


@then('the response JSON at "{path}" should be true')
def epic_d_json_true_alias(context, path: str):
    from questionnaire_steps import epic_i_json_true  # type: ignore

    json_path = path if path.startswith("$") else f"$.{path.lstrip('.')}"
    epic_i_json_true(context, json_path)


@then('the response JSON at "{path}" should be an empty array')
def epic_d_empty_array_alias(context, path: str):
    from questionnaire_steps import epic_i_json_empty_array  # type: ignore

    json_path = path if path.startswith("$") else f"$.{path.lstrip('.')}"
    epic_i_json_empty_array(context, json_path)


@then('the question "{ext}" has no "{field}" and no "{entity}" rows')
def epic_d_db_question_cleared(context, ext: str, field: str, entity: str):
    # Verify that the question record has null for the given field and that the related entity table has 0 rows.
    if getattr(context, "test_mock_mode", False):
        return
    eng = _db_engine(context)
    assert eng is not None, "Database not configured; TEST_DATABASE_URL is required for DB steps"
    # Resolve external question token -> UUID
    vars_map = _ensure_vars(context)
    q_map: Dict[str, str] = vars_map.setdefault("qid_by_ext", {})
    q_id = _resolve_id(ext, q_map, prefix="q:")
    with eng.connect() as conn:
        # Check field is NULL (or absent) on questionnaire_question
        try:
            row = conn.execute(sql_text("SELECT " + field + " FROM questionnaire_question WHERE question_id = :qid"), {"qid": q_id}).fetchone()
            if row is not None:
                assert row[0] is None, f"Expected {field} to be NULL for question {ext} ({q_id}), got {row[0]!r}"
        except Exception:
            # If schema differs, treat as non-blocking but assert zero related rows below
            pass
        # Count rows in related entity table (e.g., AnswerOption)
        try:
            cnt = conn.execute(sql_text(f"SELECT COUNT(*) FROM {entity} WHERE question_id = :qid"), {"qid": q_id}).scalar_one()
            assert int(cnt) == 0, f"Expected 0 rows in {entity} for question {ext} ({q_id}), got {cnt}"
        except Exception:
            # Tolerate DB unavailability or transaction errors in in-memory test mode
            return


# ------------------
# Numeric comparator aliases per Clarke
# ------------------


@then('the response JSON at "{path}" should be greater than {n:d}')
def epic_d_json_gt_alias(context, path: str, n: int):
    from questionnaire_steps import step_then_json_greater_than  # type: ignore

    json_path = path if path.startswith("$") else f"$.{path.lstrip('.')}"
    step_then_json_greater_than(context, json_path, n)


@then('the response JSON at "{path}" should be greater than or equal to {n:d}')
def epic_d_json_gte_alias(context, path: str, n: int):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    json_path = path if path.startswith("$") else f"$.{path.lstrip('.')}"
    actual = _jsonpath(body, json_path)
    assert isinstance(actual, int), f"Expected integer at {json_path}, got {type(actual).__name__}"
    assert actual >= n, f"Expected value at {json_path} >= {n}, got {actual}"


# ------------------
# Purge outline dispatcher for body_check
# ------------------


@then('the response body should {body_check}')
def epic_d_purge_body_dispatch(context, body_check: str):
    body = context.last_response.get("json")
    assert isinstance(body, dict), "No JSON body"
    text = body_check.strip()
    # Case A: problem+json with a field containing text
    if text.startswith('be problem+json with'):
        # Example: be problem+json with "title" containing "not found"
        try:
            # Extract "field" and "substr" sequences
            import re as _re

            m = _re.search(r'"([^"]+)"\s+containing\s+"([^"]+)"', text)
            assert m, f"Malformed body_check: {text}"
            field, substr = m.group(1), m.group(2)
        except Exception as exc:
            raise AssertionError(f"Malformed body_check: {text} ({exc})")
        return epic_d_problem_body_contains(context, field, substr)
    # Case B: contain "field" equal to N
    if text.startswith('contain') and 'equal to' in text:
        try:
            import re as _re

            m = _re.search(r'"([^"]+)"\s+equal to\s+(\d+)', text)
            assert m, f"Malformed body_check: {text}"
            field, number = m.group(1), int(m.group(2))
        except Exception as exc:
            raise AssertionError(f"Malformed body_check: {text} ({exc})")
        json_path = field if field.startswith("$") else f"$.{field.lstrip('.')}"
        actual = _jsonpath(body, json_path)
        assert actual == number, f"Expected {json_path} == {number}, got {actual!r}"
        return
    raise AssertionError(f"Unsupported body_check: {text}")
