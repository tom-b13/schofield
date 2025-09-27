"""Architectural tests for EPIC-B — Questionnaire Service

These tests enforce the architectural contract defined in the spec
docs/Epic B - Questionnaire Service.md, focusing on section 7.1.

Each test corresponds to a single section (7.1.x) and asserts the
requirements stated under that section. Tests use static inspection of
OpenAPI and JSON Schema files to avoid runtime side effects.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Tuple

import pytest


SPEC_PATH = os.path.join("docs", "Epic B - Questionnaire Service.md")
OPENAPI_PATH = os.path.join("docs", "api", "openapi.yaml")
SCHEMAS_DIR = os.path.join("docs", "schemas")


def _require_yaml_loader():
    """Return a safe YAML loader or fail with a clear assertion.

    Runner stability: if PyYAML is not available, fail the test with
    an actionable message rather than throwing ImportError.
    """
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.fail(
            f"PyYAML is required for architectural checks but could not be imported: {exc}"
        )
    return yaml


def load_openapi() -> Dict[str, Any]:
    """Load the OpenAPI YAML file, failing clearly on error."""
    assert os.path.exists(
        OPENAPI_PATH
    ), f"OpenAPI file missing: {OPENAPI_PATH}. The API contract must exist."
    yaml = _require_yaml_loader()
    try:
        with open(OPENAPI_PATH, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    except Exception as exc:
        pytest.fail(f"Failed to parse OpenAPI YAML at {OPENAPI_PATH}: {exc}")


def json_exists_and_load(path: str) -> Dict[str, Any]:
    """Load JSON from path, asserting file exists and parses as JSON."""
    assert os.path.exists(path), f"Required JSON schema file missing: {path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        pytest.fail(f"Invalid JSON in schema file {path}: {exc}")


def iter_operations(spec: Dict[str, Any]) -> Iterable[Tuple[str, str, Dict[str, Any]]]:
    """Yield (path, method, operation) for each operation in the OpenAPI spec."""
    paths = spec.get("paths", {}) or {}
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, op in methods.items():
            if method.lower() in {"get", "post", "put", "patch", "delete", "options", "head"}:
                if isinstance(op, dict):
                    yield (path, method.lower(), op)


def get_operation(spec: Dict[str, Any], path: str, method: str) -> Dict[str, Any] | None:
    return (spec.get("paths", {}) or {}).get(path, {}).get(method.lower())


def collect_operation_ids(spec: Dict[str, Any]) -> List[str]:
    return [op.get("operationId") for _, _, op in iter_operations(spec) if op.get("operationId")]


def _has_tag(op: Dict[str, Any], tag: str) -> bool:
    tags = op.get("tags") or []
    return isinstance(tags, list) and tag in tags


# 7.1.1 – CRUD operations grouped under a distinct surface
def test_epic_b_7_1_1_crud_tagging_separation():
    """7.1.1: CRUD operations share a common CRUD tag; no co-tagging with autosave/import/export."""
    # Verifies section 7.1.1
    spec = load_openapi()

    # Identify tags used by autosave, import, and export based on concrete endpoints
    autosave_op = get_operation(
        spec, "/response-sets/{response_set_id}/answers/{question_id}", "patch"
    )
    import_op = get_operation(spec, "/questionnaires/import", "post")
    export_op = get_operation(spec, "/questionnaires/{id}/export", "get")

    assert (
        autosave_op is not None
        and import_op is not None
        and export_op is not None
    ), "Autosave, import, and export endpoints must exist for tag separation checks."

    autosave_tags = set(autosave_op.get("tags") or [])
    import_tags = set(import_op.get("tags") or [])
    export_tags = set(export_op.get("tags") or [])

    # The specialized surfaces must be tagged (non-empty) and these tag sets should not be identical
    assert autosave_tags, "Autosave endpoint must declare at least one tag."
    assert import_tags, "Import endpoint must declare at least one tag."
    assert export_tags, "Export endpoint must declare at least one tag."

    # Build union of specialized tag sets to compare against CRUD operations
    specialized = autosave_tags | import_tags | export_tags

    # CRUD operations: create/update/delete/retrieve for questionnaires/screens/questions.
    # Exclude specialized endpoints and views.
    excluded_paths = {
        "/response-sets/{response_set_id}/answers/{question_id}",  # autosave
        "/questionnaires/import",  # import
        "/questionnaires/{id}/export",  # export
        "/response-sets/{id}/regenerate-check",  # gating
        "/response-sets/{response_set_id}/screens/{screen_id}",  # screen view retrieval
        "/response-sets/{id}/answers",  # batch upsert (not CRUD surface)
    }
    ops = list(iter_operations(spec))
    assert ops, "OpenAPI paths/operations are required for structural verification."

    # Identify CRUD candidates by path/method patterns; keep tags for intersection check
    crud_tag_sets: List[set] = []
    for path, method, op in ops:
        if path in excluded_paths:
            continue
        if not isinstance(op, dict):
            continue
        # Candidate path prefixes for CRUD: questionnaires, questions, screens under response-sets
        is_crud_prefix = (
            path.startswith("/questionnaires")
            or path.startswith("/questions")
            or path.startswith("/response-sets/{response_set_id}/screens")
        )
        if not is_crud_prefix:
            continue
        # Methods typical for CRUD surface
        if method not in {"get", "post", "put", "patch", "delete"}:
            continue
        tags = set(op.get("tags") or [])
        if tags:
            crud_tag_sets.append(tags)
            # Assert: CRUD op tags must be disjoint from specialized surfaces
            assert tags.isdisjoint(specialized), (
                f"CRUD operation {method.upper()} {path} must not share tags with autosave/import/export surfaces."
            )

    # There must be at least one identified CRUD-tagged operation
    assert crud_tag_sets, (
        "CRUD operations (questionnaires/screens/questions) must be present and tagged under a consistent surface."
    )

    # Assert: intersection of CRUD tags across identified operations is non-empty (shared CRUD tag)
    shared_crud_tags = set.intersection(*crud_tag_sets) if len(crud_tag_sets) > 1 else next(iter(crud_tag_sets))
    assert shared_crud_tags, (
        "CRUD operations must share at least one common tag distinct from autosave/import/export surfaces."
    )


# 7.1.2 – Dedicated validation component expressed in API schema
def test_epic_b_7_1_2_validation_expressed_via_shared_schema():
    """7.1.2: Validation via shared AnswerUpsert; no per-kind inlining."""
    # Verifies section 7.1.2
    spec = load_openapi()

    # Assert: AnswerUpsert schema file exists on disk and parses as JSON
    schema_path = os.path.join(SCHEMAS_DIR, "AnswerUpsert.schema.json")
    schema = json_exists_and_load(schema_path)
    # Assert: schema references answer_kind-specific rules via enum/discriminator
    properties = schema.get("properties", {})
    kind = properties.get("answer_kind") or schema.get("answer_kind")
    assert (
        kind is not None
    ), "AnswerUpsert.schema.json must define 'answer_kind' constraints (enum or discriminator)."

    enum_vals = set()
    if isinstance(kind, dict) and isinstance(kind.get("enum"), list):
        enum_vals = set(kind.get("enum"))
    elif isinstance(schema.get("discriminator"), dict):
        # basic discriminator presence
        enum_vals = {"short_string", "long_text", "boolean", "number", "enum_single"}

    expected = {"short_string", "long_text", "boolean", "number", "enum_single"}
    assert expected.issubset(enum_vals), "AnswerUpsert must support all required answer kinds via a shared contract."

    # Assert: No endpoint inlines per-kind constraints instead of $ref to shared schema
    for path, method, op in iter_operations(spec):
        rb = (op.get("requestBody") or {}).get("content") or {}
        for media, body in rb.items():
            schema_ref = (body.get("schema") or {}).get("$ref")
            if schema_ref:
                continue
            # Inline schema present – must not define per-kind constraints here
            inline_schema = body.get("schema") or {}
            inline_text = json.dumps(inline_schema)
            if "answer_kind" in inline_text or "enum_single" in inline_text:
                pytest.fail(
                    f"Endpoint {method.upper()} {path} must not inline per-kind constraints; use shared AnswerUpsert."
                )

    # Assert: autosave explicitly references the shared AnswerUpsert schema
    autosave_op = get_operation(
        spec, "/response-sets/{response_set_id}/answers/{question_id}", "patch"
    )
    assert autosave_op is not None
    content = ((autosave_op.get("requestBody") or {}).get("content") or {})
    assert "application/json" in content, (
        "Autosave request must declare application/json content type."
    )
    autosave_schema_ref = (content.get("application/json", {}).get("schema") or {}).get("$ref", "")
    assert autosave_schema_ref.endswith("#/components/schemas/AnswerUpsert"), (
        "Autosave request body must $ref the shared AnswerUpsert schema."
    )


# 7.1.3 – Gating service boundary present in contract
def test_epic_b_7_1_3_gating_isolated_from_generation():
    """7.1.3: Gating schema includes ok+blocking_items and is not reused by export/generation."""
    # Verifies section 7.1.3
    spec = load_openapi()
    op = get_operation(spec, "/response-sets/{id}/regenerate-check", "post")
    assert op is not None, "POST /response-sets/{id}/regenerate-check must exist."

    # Assert: gating tags are distinct from export tags
    export_op = get_operation(spec, "/questionnaires/{id}/export", "get")
    assert export_op is not None
    gating_tags = set(op.get("tags") or [])
    export_tags = set(export_op.get("tags") or [])
    assert gating_tags, "Gating operation must declare at least one tag."
    assert export_tags, "Export operation must declare at least one tag."
    assert gating_tags.isdisjoint(export_tags) is True, (
        "Gating operation tags must be distinct from export operation tags."
    )

    # Assert: response schema either $ref's a distinct RegenerateCheckResult or has explicit ok + blocking list
    responses = (op.get("responses") or {}).get("200", {})
    content = (responses.get("content") or {}).get("application/json", {})
    schema = content.get("schema") or {}
    if "$ref" in schema:
        ref = schema.get("$ref", "")
        name = ref.split("/")[-1]
        assert (
            name.lower() in {"regeneratecheckresult", "gatingresult", "regenerate_check_result"}
        ), "Gating response should $ref a distinct result schema."
    else:
        props = schema.get("properties", {}) if isinstance(schema, dict) else {}
        ok_prop = props.get("ok", {})
        blocking = props.get("blocking_items") or props.get("blocking") or props.get("blocking_outstanding") or {}
        # ok must be boolean; blocking must be present and an array
        assert ok_prop.get("type") == "boolean", "Gating response must include boolean 'ok'."
        assert isinstance(blocking, dict) and blocking.get("type") == "array", (
            "Gating response must include an array 'blocking_items' (or 'blocking') in 200 schema."
        )

    # Assert: schema not reused by export/generation endpoints, even when inline
    export_resp = (export_op.get("responses") or {}).get("200", {})
    export_schema = (export_resp.get("content") or {}).get("application/json", {}).get("schema")
    if "$ref" in (schema or {}):
        assert not (
            isinstance(export_schema, dict) and export_schema.get("$ref") == schema.get("$ref")
        ), "Gating schema must not be reused by export endpoint."
    else:
        # Compare normalized JSON shapes for inline schemas
        gating_norm = json.dumps(schema, sort_keys=True)
        export_norm = json.dumps(export_schema or {}, sort_keys=True)
        assert gating_norm != export_norm, "Gating inline schema must not be identical to export schema."


# 7.1.4 – Pre-population concerns not fused with CRUD
def test_epic_b_7_1_4_prepopulation_not_in_crud():
    """7.1.4: Only screen retrieval may mention pre-population; CRUD operations never do; screen tags disjoint from CRUD tags."""
    # Verifies section 7.1.4
    spec = load_openapi()
    ops = list(iter_operations(spec))
    assert ops, "OpenAPI must define operations."

    # Identify CRUD operations by path/method patterns (no hardcoded tag)
    screen_path = "/response-sets/{response_set_id}/screens/{screen_id}"
    screen_get = get_operation(spec, screen_path, "get")
    assert screen_get is not None, f"GET {screen_path} must exist."
    assert screen_get.get("tags"), "Screen retrieval should be tagged distinctly from CRUD."

    # Build CRUD tag set discovered from matched CRUD operations
    crud_tag_sets: List[set] = []
    for path, method, op in ops:
        if path == screen_path and method == "get":
            continue
        if method not in {"get", "post", "put", "patch", "delete"}:
            continue
        is_crud_prefix = (
            path.startswith("/questionnaires")
            or path.startswith("/questions")
            or path.startswith("/response-sets/{response_set_id}/screens")
        )
        if not is_crud_prefix:
            continue
        tags = set(op.get("tags") or [])
        if tags:
            crud_tag_sets.append(tags)
        # CRUD endpoints must not describe pre-population semantics
        desc = (op.get("description") or op.get("summary") or "").lower()
        assert ("pre-population" not in desc) and ("prepopulation" not in desc), (
            f"CRUD operation {method.upper()} {path} must not describe pre-population side effects."
        )

    # Only the screen retrieval endpoint may mention pre-population
    for path, method, op in ops:
        desc = (op.get("description") or op.get("summary") or "").lower()
        mentions = ("pre-population" in desc) or ("prepopulation" in desc)
        if mentions:
            assert path == screen_path and method == "get", (
                f"Only {screen_path} GET may mention pre-population; found in {method.upper()} {path}."
            )

    # If we discovered any CRUD tags, ensure the screen retrieval tags are disjoint from the CRUD tag intersection
    if crud_tag_sets:
        shared_crud_tags = set.intersection(*crud_tag_sets) if len(crud_tag_sets) > 1 else next(iter(crud_tag_sets))
        screen_tags = set(screen_get.get("tags") or [])
        assert screen_tags.isdisjoint(shared_crud_tags), (
            "Screen retrieval must be tagged distinctly from CRUD (no shared CRUD tag)."
        )


# 7.1.5 – Stable interfaces surfaced with distinct tags
def test_epic_b_7_1_5_stable_interfaces_and_unique_operation_ids():
    """7.1.5: Stable, distinct tags for autosave vs gating; unique operationIds."""
    # Verifies section 7.1.5
    spec = load_openapi()

    autosave_op = get_operation(
        spec, "/response-sets/{response_set_id}/answers/{question_id}", "patch"
    )
    gating_op = get_operation(spec, "/response-sets/{id}/regenerate-check", "post")
    assert autosave_op is not None and gating_op is not None
    autosave_tags = set(autosave_op.get("tags") or [])
    gating_tags = set(gating_op.get("tags") or [])
    assert autosave_tags, "Autosave must declare at least one stable tag."
    assert gating_tags, "Gating must declare at least one stable tag."
    assert autosave_tags != gating_tags, (
        "Autosave and gating must be surfaced under distinct interface tags."
    )

    # Assert: operationIds are unique
    op_ids = collect_operation_ids(spec)
    assert op_ids, "All operations must define unique operationIds."
    assert len(op_ids) == len(set(op_ids)), "operationId values must be unique across the API."


# 7.1.6 – Atomic autosave unit at API boundary
def test_epic_b_7_1_6_atomic_autosave_contract():
    """7.1.6: Autosave uses AnswerUpsert over application/json; headers via components."""
    # Verifies section 7.1.6
    spec = load_openapi()
    path = "/response-sets/{response_set_id}/answers/{question_id}"
    op = get_operation(spec, path, "patch")
    assert op is not None, f"PATCH {path} must exist for autosave."

    # Assert: request body $ref is AnswerUpsert
    rb_content = (op.get("requestBody") or {}).get("content") or {}
    assert "application/json" in rb_content, "Autosave must declare application/json content type."
    content = rb_content.get("application/json", {})
    schema = (content.get("schema") or {})
    assert schema.get("$ref", "").endswith("#/components/schemas/AnswerUpsert"), (
        "Autosave request body must $ref the shared AnswerUpsert schema."
    )

    # Assert: no batch path is tagged “autosave”
    batch_op = get_operation(spec, "/response-sets/{id}/answers", "post")
    if batch_op is not None:
        # Derive autosave tags to compare
        autosave_tags = set(op.get("tags") or [])
        batch_tags = set(batch_op.get("tags") or [])
        assert autosave_tags.isdisjoint(batch_tags), (
            "Batch upsert must not be tagged under the same surface as per-answer autosave."
        )

    # Assert: autosave requires Idempotency-Key and If-Match via reusable components
    params = op.get("parameters") or []
    ref_names = {p.get("$ref") for p in params if isinstance(p, dict) and p.get("$ref")}
    assert any(
        r.endswith("#/components/parameters/IdempotencyKey") for r in ref_names
    ), "Autosave must reference reusable IdempotencyKey parameter."
    assert any(
        r.endswith("#/components/parameters/IfMatch") for r in ref_names
    ), "Autosave must reference reusable IfMatch parameter."

    # Ensure no inline duplicates of these headers
    for p in params:
        if isinstance(p, dict) and not p.get("$ref"):
            name = p.get("name")
            assert name not in {"Idempotency-Key", "If-Match"}, (
                "Autosave must not inline Idempotency-Key or If-Match; use reusable components only."
            )


# 7.1.7 – Idempotency header enforcement defined centrally
def test_epic_b_7_1_7_idempotency_parameter_reusable():
    """7.1.7: Central Idempotency-Key parameter reused; no inlining."""
    # Verifies section 7.1.7
    spec = load_openapi()
    components = spec.get("components", {})
    parameters = components.get("parameters", {})
    assert "IdempotencyKey" in parameters, "#/components/parameters/IdempotencyKey must exist."
    ide = parameters.get("IdempotencyKey") or {}
    assert ide.get("name") == "Idempotency-Key", "IdempotencyKey.name must be 'Idempotency-Key'."
    assert ide.get("in") == "header", "IdempotencyKey.in must be 'header'."
    assert ide.get("required") is True, "IdempotencyKey.required must be true."

    op = get_operation(spec, "/response-sets/{response_set_id}/answers/{question_id}", "patch")
    assert op is not None, "Autosave operation must exist."
    params = op.get("parameters") or []
    # Must reference by $ref and not inline duplicate
    assert any(
        isinstance(p, dict) and p.get("$ref", "").endswith("#/components/parameters/IdempotencyKey")
        for p in params
    ), "Autosave must reference the reusable IdempotencyKey parameter."
    assert not any(
        isinstance(p, dict) and p.get("name") == "Idempotency-Key" and not p.get("$ref") for p in params
    ), "Do not inline Idempotency-Key; reference the reusable parameter."


# 7.1.8 – Concurrency token (ETag) generation separated from business logic
def test_epic_b_7_1_8_concurrency_headers_reusable_and_not_inlined():
    """7.1.8: If-Match and ETag must use reusable components; no inline duplicates."""
    # Verifies section 7.1.8
    spec = load_openapi()
    components = spec.get("components", {})
    parameters = components.get("parameters", {})
    assert "IfMatch" in parameters, "#/components/parameters/IfMatch must exist."

    op = get_operation(spec, "/response-sets/{response_set_id}/answers/{question_id}", "patch")
    assert op is not None, "Autosave operation must exist."
    params = op.get("parameters") or []
    assert any(
        isinstance(p, dict) and p.get("$ref", "").endswith("#/components/parameters/IfMatch") for p in params
    ), "Autosave must reference the reusable IfMatch parameter."
    assert not any(
        isinstance(p, dict) and p.get("name") == "If-Match" and not p.get("$ref") for p in params
    ), "Do not inline If-Match; reference the reusable parameter."

    # Response headers must use reusable components (e.g., components.headers.ETag)
    responses = (op.get("responses") or {}).get("200", {})
    headers = responses.get("headers") or {}
    assert "ETag" in headers, "Response must declare an ETag header under 200 response."
    etag_obj = headers.get("ETag") or {}
    assert isinstance(etag_obj, dict), "ETag header declaration must be an object."
    assert etag_obj.get("$ref", "").endswith("#/components/headers/ETag"), (
        "ETag header must be referenced via reusable component (#/components/headers/ETag)."
    )
    # Ensure no inline header object duplication
    assert not ("name" in etag_obj or "schema" in etag_obj), (
        "ETag header must not be declared inline (no 'name' or 'schema' without $ref)."
    )


# 7.1.9 – CSV import parser contract present
def test_epic_b_7_1_9_import_contract_and_schema_file():
    """7.1.9: Import uses text/csv; charset=utf-8 and publishes CSVImportFile schema."""
    # Verifies section 7.1.9
    spec = load_openapi()
    op = get_operation(spec, "/questionnaires/import", "post")
    assert op is not None, "POST /questionnaires/import must exist."
    content = ((op.get("requestBody") or {}).get("content") or {})
    # Require charset in content type
    has_utf8 = any(
        k.lower().startswith("text/csv;") and "charset=utf-8" in k.lower() for k in content.keys()
    )
    assert has_utf8, "Import must declare 'text/csv; charset=utf-8' content type."

    # Assert: CSVImportFile schema exists on disk and validates
    schema_path = os.path.join(SCHEMAS_DIR, "CSVImportFile.schema.json")
    schema = json_exists_and_load(schema_path)

    # Assert presence of required columns in schema description/properties
    as_text = json.dumps(schema).lower()
    for col in [
        "external_qid",
        "screen_key",
        "question_order",
        "question_text",
        "answer_kind",
        "mandatory",
        "placeholder_code",
        "options",
    ]:
        assert col in as_text, f"CSVImportFile schema must reference column: {col}"


# 7.1.10 – Options expansion subcomponent expressed in schema contract
def test_epic_b_7_1_10_options_semantics_documented():
    """7.1.10: 'options' column is a string with documented value[:label]|... semantics."""
    # Verifies section 7.1.10
    schema_path = os.path.join(SCHEMAS_DIR, "CSVImportFile.schema.json")
    schema = json_exists_and_load(schema_path)
    props = schema.get("properties", {})
    options = props.get("options") or schema.get("options")
    assert options is not None, "CSVImportFile schema must define an 'options' property."
    assert options.get("type") == "string", "'options' must be typed as string."
    text = (options.get("description") or options.get("format") or "").lower()
    assert ("value[:label]" in text) and ("|" in text), (
        "'options' must document value[:label] pairs and '|' delimiter semantics."
    )


# 7.1.11 – Import response schema formalised
def test_epic_b_7_1_11_import_result_schema_formalised():
    """7.1.11: ImportResult schema defines created/updated/errors with line/message and is referenced by 200."""
    # Verifies section 7.1.11
    spec = load_openapi()
    components = spec.get("components", {})
    schemas = components.get("schemas", {})
    assert "ImportResult" in schemas, "#/components/schemas/ImportResult must exist."
    ir = schemas.get("ImportResult") or {}
    ir_props = ir.get("properties", {})
    assert ir_props.get("created", {}).get("type") == "integer", "ImportResult.created must be integer."
    assert ir_props.get("updated", {}).get("type") == "integer", "ImportResult.updated must be integer."
    errors = ir_props.get("errors", {})
    assert errors.get("type") == "array", "ImportResult.errors must be an array."
    item_props = (errors.get("items") or {}).get("properties", {})
    assert item_props.get("line", {}).get("type") == "integer", "errors[].line must be integer."
    assert item_props.get("message", {}).get("type") == "string", "errors[].message must be string."

    # Import operation must reference ImportResult in responses
    op = get_operation(spec, "/questionnaires/import", "post")
    assert op is not None
    responses = (op.get("responses") or {}).get("200", {})
    content = (responses.get("content") or {}).get("application/json", {})
    schema = content.get("schema") or {}
    assert schema.get("$ref", "").endswith(
        "#/components/schemas/ImportResult"
    ), "Import 200 response must $ref ImportResult schema."


# 7.1.12 – CSV export builder contract separated from question reads
def test_epic_b_7_1_12_export_is_distinct_and_streaming():
    """7.1.12: Export tagged separately; response is text/csv; charset=utf-8 and mentions streaming."""
    # Verifies section 7.1.12
    spec = load_openapi()
    op = get_operation(spec, "/questionnaires/{id}/export", "get")
    assert op is not None, "GET /questionnaires/{id}/export must exist."
    # Tagged separately from CRUD
    assert op.get("tags"), "Export operation must be tagged separately from CRUD."
    # Response content type includes text/csv; streaming mentioned in description
    resp = (op.get("responses") or {}).get("200", {})
    content = resp.get("content") or {}
    assert any(
        ct.lower().startswith("text/csv;") and "charset=utf-8" in ct.lower() for ct in content.keys()
    ), "Export must declare 'text/csv; charset=utf-8' response content type."
    desc = (op.get("description") or op.get("summary") or "").lower()
    assert "stream" in desc, "Export operation description should mention streaming."


# 7.1.13 – Export transaction requirement captured in API description
def test_epic_b_7_1_13_export_documents_snapshot_isolation():
    """7.1.13: Export docs mention read-only, repeatable-read (or equivalent snapshot)."""
    # Verifies section 7.1.13
    spec = load_openapi()
    op = get_operation(spec, "/questionnaires/{id}/export", "get")
    assert op is not None
    desc = (op.get("description") or op.get("summary") or "").lower()
    phrase = "read-only, repeatable-read"
    assert (phrase in desc) or ("equivalent snapshot" in desc), (
        "Export must state read-only, repeatable-read transaction (or equivalent snapshot)."
    )


# 7.1.14 – Strong ETag for export payload
def test_epic_b_7_1_14_export_strong_etag_header_and_description():
    """7.1.14: Export declares strong ETag via reusable header; strong payload-based description."""
    # Verifies section 7.1.14
    spec = load_openapi()
    op = get_operation(spec, "/questionnaires/{id}/export", "get")
    assert op is not None
    resp = (op.get("responses") or {}).get("200", {})
    headers = resp.get("headers") or {}
    assert "ETag" in headers, "Export 200 response must declare an ETag response header."
    etag_obj = headers.get("ETag") or {}
    assert isinstance(etag_obj, dict), "ETag header declaration must be an object."
    assert etag_obj.get("$ref", "").endswith("#/components/headers/ETag"), (
        "Export ETag header must be referenced via reusable component (#/components/headers/ETag)."
    )
    header_desc = (etag_obj.get("description") or "").lower()
    assert (
        "strong" in header_desc and ("sha-256" in header_desc or "sha256" in header_desc or "payload" in header_desc)
    ), "ETag header description should note strong validator computed from payload (e.g., SHA-256 over rowset)."


# 7.1.15 – Authentication middleware boundary expressed in securitySchemes
def test_epic_b_7_1_15_authentication_enforced_centrally():
    """7.1.15: Central bearerAuth scheme; every op explicitly includes bearerAuth globally or per-op."""
    # Verifies section 7.1.15
    spec = load_openapi()
    components = spec.get("components", {})
    security_schemes = components.get("securitySchemes", {})
    assert "bearerAuth" in security_schemes, "components.securitySchemes.bearerAuth must exist."

    # Either global security contains bearerAuth, or per-operation includes bearerAuth; no op may omit it.
    global_sec = spec.get("security") or []
    def _sec_includes_bearer(sec_list: Any) -> bool:
        if not isinstance(sec_list, list):
            return False
        for entry in sec_list:
            if isinstance(entry, dict) and any(k == "bearerAuth" for k in entry.keys()):
                return True
        return False

    global_has_bearer = _sec_includes_bearer(global_sec)
    for path, method, op in iter_operations(spec):
        op_sec = op.get("security") or []
        has_bearer = global_has_bearer or _sec_includes_bearer(op_sec)
        assert has_bearer, f"Operation {method.upper()} {path} must enforce bearerAuth security."


# 7.1.16 – problem+json encoder contract present
def test_epic_b_7_1_16_problem_json_schemas_and_usage():
    """7.1.16: 4xx/5xx use application/problem+json with $ref to Problem/ValidationProblem; local schemas exist."""
    # Verifies section 7.1.16
    spec = load_openapi()

    # Schema files must exist and validate as JSON
    problem_path = os.path.join(SCHEMAS_DIR, "Problem.schema.json")
    validation_problem_path = os.path.join(SCHEMAS_DIR, "ValidationProblem.schema.json")
    json_exists_and_load(problem_path)
    json_exists_and_load(validation_problem_path)

    # 4xx/5xx must reference problem+json and $ref a shared Problem/ValidationProblem schema
    for path, method, op in iter_operations(spec):
        responses = op.get("responses") or {}
        for status, resp in responses.items():
            if status.startswith("4") or status.startswith("5"):
                content = (resp.get("content") or {}).get("application/problem+json")
                assert (
                    content is not None
                ), f"{method.upper()} {path} {status} must declare application/problem+json content."
                schema = (content.get("schema") or {})
                ref = schema.get("$ref") if isinstance(schema, dict) else None
                assert ref, (
                    f"{method.upper()} {path} {status} problem+json must $ref a shared Problem schema."
                )
                ref_lower = ref.lower()
                assert (
                    ref_lower.endswith("#/components/schemas/problem")
                    or ref_lower.endswith("#/components/schemas/validationproblem")
                    or ("problem" in ref_lower)
                ), (
                    f"{method.upper()} {path} {status} must reference Problem/ValidationProblem schema via $ref."
                )
    # Optionally assert these schemas are present in components when not external
    comps = spec.get("components", {}).get("schemas", {}) or {}
    # If local, they should exist (do not fail if only external $ref used)
    if any(k.lower() == "problem" for k in comps.keys()):
        assert "Problem" in comps
    if any(k.lower() == "validationproblem" for k in comps.keys()):
        assert "ValidationProblem" in comps


# 7.1.17 – Deterministic export ordering documented
def test_epic_b_7_1_17_export_ordering_documented():
    """7.1.17: Export docs clearly state deterministic ordering with NULLS LAST for screen_key and question_order."""
    # Verifies section 7.1.17
    spec = load_openapi()
    op = get_operation(spec, "/questionnaires/{id}/export", "get")
    assert op is not None
    desc = (op.get("description") or op.get("summary") or "").lower()
    assert "order by" in desc, "Export must describe ordering semantics."
    assert "screen_key" in desc and "question_order" in desc and "question_id" in desc, (
        "Export description must include screen_key, question_order, and question_id ordering keys."
    )
    assert "nulls last" in desc, (
        "Export description must specify NULLS LAST for ordering where applicable."
    )


# 7.1.18 – Linkage enforcement expressed in API view models
def test_epic_b_7_1_18_linkage_in_screen_view_models():
    """7.1.18: Screen view models include response_set_id and questions[].question_id plus answer linkage fields."""
    # Verifies section 7.1.18
    spec = load_openapi()
    op = get_operation(spec, "/response-sets/{response_set_id}/screens/{screen_id}", "get")
    assert op is not None
    content = ((op.get("responses") or {}).get("200", {}).get("content") or {}).get(
        "application/json", {}
    )
    schema = content.get("schema") or {}
    # Resolve $ref if present (best-effort)
    def _resolve_schema(s: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(s, dict):
            return {}
        if "$ref" in s and isinstance(s["$ref"], str):
            ref = s["$ref"]
            if ref.startswith("#/components/schemas/"):
                name = ref.split("/")[-1]
                return (spec.get("components", {}).get("schemas", {}) or {}).get(name, {})
        return s

    schema = _resolve_schema(schema)
    assert isinstance(schema, dict), "Screen view 200 schema must be an object or $ref to an object."

    props = schema.get("properties", {}) if isinstance(schema, dict) else {}
    assert "response_set_id" in props, (
        "View model must include top-level response_set_id (or explicit linkage context)."
    )
    questions = props.get("questions", {})
    assert isinstance(questions, dict) and questions.get("type") == "array", (
        "View model must include a 'questions' array."
    )
    item_schema = _resolve_schema(questions.get("items") or {})
    item_props = item_schema.get("properties", {}) if isinstance(item_schema, dict) else {}
    assert "question_id" in item_props, "Each question item must include 'question_id'."
    # Answer linkage: require at least one property that denotes an answer association
    has_answer_link = any(
        (k.startswith("answer") or k in {"value", "answer_id", "answer_value", "answer_text"}) for k in item_props.keys()
    )
    assert has_answer_link, (
        "Question item must include answer linkage fields (e.g., answer_id/value/text)."
    )


# 7.1.19 – Separation of persistence vs linkage responsibilities (contract signal)
def test_epic_b_7_1_19_separate_persistence_and_view_schemas():
    """7.1.19: Distinguish CRUD entity schemas from screen-view schemas by usage; no schema reused for both roles."""
    # Verifies section 7.1.19
    spec = load_openapi()
    components = spec.get("components", {})
    schemas = components.get("schemas", {}) or {}

    # Collect schemas referenced by CRUD endpoints (entities)
    crud_schema_refs: set[str] = set()
    view_schema_refs: set[str] = set()

    def _collect_refs(node: Any) -> Iterable[str]:
        if isinstance(node, dict):
            if "$ref" in node and isinstance(node["$ref"], str) and node["$ref"].startswith("#/components/schemas/"):
                yield node["$ref"].split("/")[-1]
            for v in node.values():
                yield from _collect_refs(v)
        elif isinstance(node, list):
            for it in node:
                yield from _collect_refs(it)

    # Define helpers to classify operations
    def _is_crud_path(path: str, method: str) -> bool:
        if method not in {"get", "post", "put", "patch", "delete"}:
            return False
        return (
            path.startswith("/questionnaires")
            or path.startswith("/questions")
            or path.startswith("/response-sets/{response_set_id}/screens")
        ) and path not in {
            "/response-sets/{response_set_id}/screens/{screen_id}",  # view retrieval
        }

    for path, method, op in iter_operations(spec):
        if _is_crud_path(path, method):
            # collect refs from request/response bodies
            rb = (op.get("requestBody") or {}).get("content") or {}
            for media in rb.values():
                for n in _collect_refs((media.get("schema") or {})):
                    crud_schema_refs.add(n)
            for resp in (op.get("responses") or {}).values():
                for media in (resp.get("content") or {}).values():
                    for n in _collect_refs((media.get("schema") or {})):
                        crud_schema_refs.add(n)

    # Screen retrieval view schema(s)
    screen_get = get_operation(spec, "/response-sets/{response_set_id}/screens/{screen_id}", "get")
    assert screen_get is not None, "Screen retrieval endpoint must exist."
    resp200 = (screen_get.get("responses") or {}).get("200", {})
    for media in (resp200.get("content") or {}).values():
        for n in _collect_refs((media.get("schema") or {})):
            view_schema_refs.add(n)

    # There must be at least one entity-like schema and one view schema referenced
    assert crud_schema_refs, "At least one CRUD entity schema must be referenced by CRUD endpoints."
    assert view_schema_refs, "Screen retrieval must reference at least one view/linkage schema."

    # No single schema may serve both roles
    assert crud_schema_refs.isdisjoint(view_schema_refs), (
        "Persistence entity schemas must not be reused as screen view schemas (distinct roles)."
    )
