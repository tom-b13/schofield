"""Architectural tests for EPIC I — Conditional Visibility

These tests enforce the architectural contract defined in
docs/Epic I - Conditional Visibility.md, specifically section 7.1.

Each test corresponds to a single section (7.1.x) and asserts the
requirements stated under that section. Tests use static inspection of
OpenAPI and JSON Schema files to avoid runtime side effects.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Iterable, List, Tuple

import pytest


SPEC_PATH = os.path.join("docs", "Epic I - Conditional Visibility.md")
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
    """Load JSON from path, asserting file exists and parses as JSON.

    Runner stability: if the file is missing or invalid, fail with a clear
    assertion instead of raising.
    """
    assert os.path.exists(path), f"Required JSON schema file missing: {path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        pytest.fail(f"Invalid JSON in schema file {path}: {exc}")


def _prop(schema: Dict[str, Any], name: str) -> Dict[str, Any]:
    props = schema.get("properties", {}) or {}
    assert isinstance(props, dict), "Schema 'properties' must be an object."
    return props.get(name) or {}


def _collect_allowed_types(s: Dict[str, Any]) -> List[str]:
    """Return the set of allowed JSON Schema types for a property.

    Supports 'type' as string or list, and compositions via oneOf/anyOf/allOf.
    """
    types: List[str] = []
    t = s.get("type")
    if isinstance(t, str):
        types.append(t)
    elif isinstance(t, list):
        types.extend([x for x in t if isinstance(x, str)])

    for key in ("oneOf", "anyOf", "allOf"):
        variants = s.get(key) or []
        if isinstance(variants, list):
            for v in variants:
                if isinstance(v, dict):
                    vt = v.get("type")
                    if isinstance(vt, str):
                        types.append(vt)
                    elif isinstance(vt, list):
                        types.extend([x for x in vt if isinstance(x, str)])
    # De-duplicate while preserving order
    seen = set()
    deduped: List[str] = []
    for x in types:
        if x not in seen:
            seen.add(x)
            deduped.append(x)
    return deduped


def _allows_null(s: Dict[str, Any]) -> bool:
    types = set(_collect_allowed_types(s))
    return s.get("nullable") is True or ("null" in types)


def _is_uuid_string_schema(s: Dict[str, Any]) -> bool:
    types = set(_collect_allowed_types(s))
    fmt = s.get("format")
    return ("string" in types) and (fmt == "uuid")


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


# 7.1.1 — QuestionnaireQuestion visibility fields exist
def test_epic_i_7_1_1_questionnairequestion_visibility_fields_exist():
    """7.1.1: QuestionnaireQuestion exposes parent_question_id and visible_if_value with required typing."""
    # Verifies section 7.1.1
    schema_path = os.path.join(SCHEMAS_DIR, "QuestionnaireQuestion.schema.json")
    schema = json_exists_and_load(schema_path)

    # Assert: parent_question_id is string uuid and allows null
    parent = _prop(schema, "parent_question_id")
    assert parent, "Schema must define properties.parent_question_id."
    # type string + format uuid
    assert _is_uuid_string_schema(
        parent
    ), "parent_question_id must be type 'string' with format 'uuid'."
    # allows null via nullable or union including 'null'
    assert _allows_null(parent), (
        "parent_question_id must be nullable (type union including 'null' or nullable: true)."
    )

    # Assert: visible_if_value permits exactly null, string, or array of strings
    vif = _prop(schema, "visible_if_value")
    assert vif, "Schema must define properties.visible_if_value."
    allowed = set(_collect_allowed_types(vif))
    assert allowed, (
        "visible_if_value must constrain allowed types (string/array/null); found none."
    )
    # No extraneous types beyond {'string','array','null'}
    assert allowed.issubset({"string", "array", "null"}), (
        f"visible_if_value types must be subset of string|array|null; got {sorted(allowed)}"
    )
    # If array is allowed, its items must be strings
    if "array" in allowed:
        items = vif.get("items") or {}
        assert isinstance(items, dict) and (
            (items.get("type") == "string") or (items.get("type") in ["string"])  # explicit
        ), "visible_if_value array items must be type string."


# 7.1.2 — Response canonical value fields exist
def test_epic_i_7_1_2_response_canonical_fields_exist():
    """7.1.2: Response schema exposes canonical fields option_id/value_bool/value_number/value_text (nullable)."""
    # Verifies section 7.1.2
    schema_path = os.path.join(SCHEMAS_DIR, "Response.schema.json")
    schema = json_exists_and_load(schema_path)

    # option_id: string uuid (nullable allowed)
    option_id = _prop(schema, "option_id")
    assert option_id, "Response must define properties.option_id."
    assert _is_uuid_string_schema(option_id), (
        "option_id must be type 'string' with format 'uuid'."
    )

    # value_bool: boolean (nullable allowed)
    value_bool = _prop(schema, "value_bool")
    assert value_bool, "Response must define properties.value_bool."
    assert "boolean" in _collect_allowed_types(value_bool), (
        "value_bool must allow type 'boolean'."
    )

    # value_number: number (nullable allowed)
    value_number = _prop(schema, "value_number")
    assert value_number, "Response must define properties.value_number."
    assert "number" in _collect_allowed_types(value_number), (
        "value_number must allow type 'number'."
    )

    # value_text: string (nullable allowed)
    value_text = _prop(schema, "value_text")
    assert value_text, "Response must define properties.value_text."
    assert "string" in _collect_allowed_types(value_text), (
        "value_text must allow type 'string'."
    )


# 7.1.3 — AnswerOption canonical value field exists
def test_epic_i_7_1_3_answer_option_canonical_value_field_exists():
    """7.1.3: AnswerOption schema exposes canonical 'value' as required string."""
    # Verifies section 7.1.3
    schema_path = os.path.join(SCHEMAS_DIR, "AnswerOption.schema.json")
    schema = json_exists_and_load(schema_path)

    val = _prop(schema, "value")
    assert val, "AnswerOption must define properties.value."
    assert val.get("type") == "string", "AnswerOption.value must be type 'string'."
    required = schema.get("required") or []
    assert isinstance(required, list) and "value" in required, (
        "AnswerOption.value must be present in the schema 'required' array."
    )


# 7.1.4 — ScreenView excludes rule/hidden containers
def test_epic_i_7_1_4_screen_view_excludes_rule_hidden_containers():
    """7.1.4: ScreenView lists visible questions only; no hidden/visibility rules containers present."""
    # Verifies section 7.1.4
    schema_path = os.path.join(SCHEMAS_DIR, "ScreenView.schema.json")
    schema = json_exists_and_load(schema_path)

    props = schema.get("properties", {}) or {}
    assert isinstance(props, dict), "ScreenView schema must define an object with properties."

    # Assert: questions collection is defined (array)
    questions = props.get("questions") or {}
    assert isinstance(questions, dict) and questions.get("type") == "array", (
        "ScreenView must define properties.questions as an array."
    )
    assert "items" in questions, "ScreenView.questions must define 'items'."

    # Assert: no hidden containers or rules present
    forbidden = {"hidden_questions", "visibility_rules"}
    present_forbidden = sorted([k for k in props.keys() if k in forbidden])
    assert not present_forbidden, (
        f"ScreenView.properties must not contain {forbidden}; found: {present_forbidden}"
    )


# 7.1.5 — AutosaveResult.suppressed_answers[] defined
def test_epic_i_7_1_5_autosave_result_suppressed_answers_defined():
    """7.1.5: AutosaveResult defines suppressed_answers as array of QuestionId (string uuid)."""
    # Verifies section 7.1.5
    schema_path = os.path.join(SCHEMAS_DIR, "AutosaveResult.schema.json")
    schema = json_exists_and_load(schema_path)

    sa = _prop(schema, "suppressed_answers")
    assert sa, "AutosaveResult must define properties.suppressed_answers."
    assert sa.get("type") == "array", "suppressed_answers must be an array."
    items = sa.get("items") or {}
    assert isinstance(items, dict), "suppressed_answers.items must be an object schema."
    # items: either string+uuid or $ref to QuestionId
    is_uuid_items = (items.get("type") == "string" and items.get("format") == "uuid")
    is_qid_ref = isinstance(items.get("$ref"), str) and ("QuestionId" in items.get("$ref"))
    assert is_uuid_items or is_qid_ref, (
        "suppressed_answers.items must be string uuid or $ref to QuestionId schema."
    )
    # suppressed_answers optional (not required)
    required = schema.get("required") or []
    assert "suppressed_answers" not in (required or []), (
        "suppressed_answers must be optional (not listed in required)."
    )


# 7.1.6 — AutosaveResult.visibility_delta.* defined
def test_epic_i_7_1_6_autosave_result_visibility_delta_defined():
    """7.1.6: AutosaveResult defines visibility_delta with now_visible/now_hidden arrays of QuestionId."""
    # Verifies section 7.1.6
    schema_path = os.path.join(SCHEMAS_DIR, "AutosaveResult.schema.json")
    schema = json_exists_and_load(schema_path)

    vd = _prop(schema, "visibility_delta")
    assert vd, "AutosaveResult must define properties.visibility_delta."
    assert vd.get("type") == "object", "visibility_delta must be an object."
    vprops = vd.get("properties", {}) or {}
    assert isinstance(vprops, dict), "visibility_delta.properties must be present."

    # now_visible array of QuestionId
    nv = vprops.get("now_visible") or {}
    assert nv.get("type") == "array", "visibility_delta.now_visible must be an array."
    nv_items = nv.get("items") or {}
    nv_uuid = nv_items.get("type") == "string" and nv_items.get("format") == "uuid"
    nv_ref = isinstance(nv_items.get("$ref"), str) and ("QuestionId" in nv_items.get("$ref"))
    assert nv_uuid or nv_ref, (
        "now_visible items must be string uuid or $ref to QuestionId schema."
    )

    # now_hidden array of QuestionId
    nh = vprops.get("now_hidden") or {}
    assert nh.get("type") == "array", "visibility_delta.now_hidden must be an array."
    nh_items = nh.get("items") or {}
    nh_uuid = nh_items.get("type") == "string" and nh_items.get("format") == "uuid"
    nh_ref = isinstance(nh_items.get("$ref"), str) and ("QuestionId" in nh_items.get("$ref"))
    assert nh_uuid or nh_ref, (
        "now_hidden items must be string uuid or $ref to QuestionId schema."
    )

    # visibility_delta optional (not required)
    required = schema.get("required") or []
    assert "visibility_delta" not in (required or []), (
        "visibility_delta must be optional (not listed in required)."
    )


# 7.1.7 — FeatureOutputs schema enforces deterministic keys
def test_epic_i_7_1_7_feature_outputs_schema_deterministic_keys():
    """7.1.7: FeatureOutputs sets additionalProperties=false and enumerates only allowed keys."""
    # Verifies section 7.1.7
    schema_path = os.path.join(SCHEMAS_DIR, "FeatureOutputs.schema.json")
    schema = json_exists_and_load(schema_path)

    # additionalProperties must be false at the top level
    assert schema.get("additionalProperties") is False, (
        "FeatureOutputs must set additionalProperties: false at the top level."
    )
    props = schema.get("properties", {}) or {}
    assert isinstance(props, dict) and props, (
        "FeatureOutputs.properties must enumerate allowed keys."
    )
    assert "patternProperties" not in schema, (
        "FeatureOutputs must not use patternProperties for top-level keys."
    )


# 7.1.8 — AutosaveResult includes etag
def test_epic_i_7_1_8_autosave_result_includes_etag():
    """7.1.8: AutosaveResult exposes string etag and the PATCH 2xx response schema requires it."""
    # Verifies section 7.1.8
    # 1) Check the AutosaveResult schema defines an etag string
    schema_path = os.path.join(SCHEMAS_DIR, "AutosaveResult.schema.json")
    schema = json_exists_and_load(schema_path)

    # Assert: etag property exists and is a string
    etag = _prop(schema, "etag")
    assert etag, "AutosaveResult must define properties.etag."
    assert etag.get("type") == "string", "etag must be type 'string'."

    # 2) Validate that the OpenAPI PATCH success response references a schema that requires 'etag'
    spec = load_openapi()
    components = spec.get("components", {}) or {}
    comp_schemas = components.get("schemas", {}) or {}

    def resolve_ref(ref: str) -> Dict[str, Any]:
        # Only resolve local component schema refs for this assertion
        if not ref.startswith("#/components/schemas/"):
            pytest.fail(
                f"PATCH success response must $ref a local components schema; got: {ref}"
            )
        name = ref.split("/")[-1]
        resolved = comp_schemas.get(name)
        assert isinstance(resolved, dict) and resolved, (
            f"Missing referenced schema at components.schemas.{name}"
        )
        return resolved

    patch_path = "/response-sets/{response_set_id}/answers/{question_id}"
    op = get_operation(spec, patch_path, "patch")
    assert op is not None, f"PATCH {patch_path} must exist."
    responses = op.get("responses") or {}
    # Locate a 2xx JSON response
    success_codes = [k for k in responses.keys() if str(k).startswith("2")]
    assert success_codes, f"PATCH {patch_path} must define a 2xx success response."
    # Prefer 200 if present for determinism
    code = "200" if "200" in success_codes else sorted(success_codes)[0]
    success = responses.get(code) or {}
    content = (success.get("content") or {}).get("application/json") or {}
    assert content, (
        f"PATCH {patch_path} {code} must define application/json content."
    )
    resp_schema = content.get("schema") or {}

    # Resolve one level of $ref if present
    if "$ref" in resp_schema:
        resp_schema = resolve_ref(resp_schema["$ref"])  # resolved schema object

    # The schema actually referenced for the PATCH success response must require 'etag'
    required = resp_schema.get("required") or []
    assert isinstance(required, list) and ("etag" in required), (
        "PATCH success response schema must include 'etag' in its required array."
    )


# 7.1.9 — OpenAPI defines If-Match parameter for PATCH
def test_epic_i_7_1_9_openapi_defines_if_match_parameter_for_patch():
    """7.1.9: OpenAPI declares reusable If-Match header and references it from PATCH autosave."""
    # Verifies section 7.1.9
    spec = load_openapi()

    components = spec.get("components", {}) or {}
    params = components.get("parameters", {}) or {}
    assert "IfMatch" in params, "#/components/parameters/IfMatch must exist."
    ifm = params.get("IfMatch") or {}
    assert ifm.get("in") == "header", "IfMatch.in must be 'header'."
    assert ifm.get("name") == "If-Match", "IfMatch.name must be 'If-Match'."
    schema = ifm.get("schema") or {}
    assert schema.get("type") == "string", "IfMatch.schema.type must be 'string'."

    # PATCH operation must reference the parameter
    path = "/response-sets/{response_set_id}/answers/{question_id}"
    op = get_operation(spec, path, "patch")
    assert op is not None, f"PATCH {path} must exist."
    op_params = op.get("parameters") or []
    assert any(
        isinstance(p, dict) and p.get("$ref", "").endswith("#/components/parameters/IfMatch") for p in op_params
    ), "PATCH autosave must reference #/components/parameters/IfMatch via $ref."


# 7.1.10 — OpenAPI defines Idempotency-Key parameter for PATCH
def test_epic_i_7_1_10_openapi_defines_idempotency_key_for_patch():
    """7.1.10: OpenAPI declares reusable Idempotency-Key header and references it from PATCH autosave."""
    # Verifies section 7.1.10
    spec = load_openapi()

    components = spec.get("components", {}) or {}
    params = components.get("parameters", {}) or {}
    assert "IdempotencyKey" in params, "#/components/parameters/IdempotencyKey must exist."
    ide = params.get("IdempotencyKey") or {}
    assert ide.get("in") == "header", "IdempotencyKey.in must be 'header'."
    assert ide.get("name") == "Idempotency-Key", "IdempotencyKey.name must be 'Idempotency-Key'."
    schema = ide.get("schema") or {}
    assert schema.get("type") == "string", "IdempotencyKey.schema.type must be 'string'."

    # PATCH operation must reference the parameter
    path = "/response-sets/{response_set_id}/answers/{question_id}"
    op = get_operation(spec, path, "patch")
    assert op is not None, f"PATCH {path} must exist."
    op_params = op.get("parameters") or []
    assert any(
        isinstance(p, dict) and p.get("$ref", "").endswith("#/components/parameters/IdempotencyKey")
        for p in op_params
    ), "PATCH autosave must reference #/components/parameters/IdempotencyKey via $ref."


# 7.1.11 — OpenAPI error responses use problem+json
def test_epic_i_7_1_11_openapi_error_responses_use_problem_json():
    """7.1.11: GET screen and PATCH autosave declare 404/409/422 with application/problem+json using Problem schema."""
    # Verifies section 7.1.11
    spec = load_openapi()

    # Problem schema exists internally OR responses may reference an external Problem schema file
    components = spec.get("components", {}) or {}
    schemas = components.get("schemas", {}) or {}
    has_internal_problem = "Problem" in schemas

    def is_problem_ref(ref: str) -> bool:
        # Accept either internal component ref or external file path ending with schemas/Problem.schema.json
        return (
            ref.endswith("#/components/schemas/Problem")
            or ref.endswith("schemas/Problem.schema.json")
            or "/schemas/Problem.schema.json" in ref
        )

    # GET screen endpoint errors
    get_path = "/response-sets/{response_set_id}/screens/{screen_id}"
    get_op = get_operation(spec, get_path, "get")
    assert get_op is not None, f"GET {get_path} must exist."
    for code in ["404", "422"]:
        resp = (get_op.get("responses") or {}).get(code) or {}
        assert resp, f"GET {get_path} must define {code} response."
        content = (resp.get("content") or {}).get("application/problem+json") or {}
        assert content, f"GET {get_path} {code} must declare application/problem+json content."
        schema = content.get("schema") or {}
        ref = schema.get("$ref", "")
        assert ref, f"GET {get_path} {code} must reference a Problem schema via $ref."
        assert is_problem_ref(ref), (
            f"GET {get_path} {code} must reference Problem schema (internal or external)."
        )

    # PATCH autosave endpoint errors
    patch_path = "/response-sets/{response_set_id}/answers/{question_id}"
    patch_op = get_operation(spec, patch_path, "patch")
    assert patch_op is not None, f"PATCH {patch_path} must exist."
    for code in ["404", "409", "422"]:
        resp = (patch_op.get("responses") or {}).get(code) or {}
        assert resp, f"PATCH {patch_path} must define {code} response."
        content = (resp.get("content") or {}).get("application/problem+json") or {}
        assert content, f"PATCH {patch_path} {code} must declare application/problem+json content."
        schema = content.get("schema") or {}
        ref = schema.get("$ref", "")
        assert ref, f"PATCH {patch_path} {code} must reference a Problem schema via $ref."
        assert is_problem_ref(ref), (
            f"PATCH {patch_path} {code} must reference Problem schema (internal or external)."
        )

    # At least one of: an internal Problem schema exists, or responses used an external reference.
    # This ensures the API contract provides a Problem schema definition one way or another.
    used_external = False
    for op_path, method, op in iter_operations(spec):
        for code, resp in (op.get("responses") or {}).items():
            content = (resp.get("content") or {}).get("application/problem+json") or {}
            schema = content.get("schema") or {}
            ref = schema.get("$ref")
            if isinstance(ref, str) and ("Problem.schema.json" in ref):
                used_external = True
                break
        if used_external:
            break
    assert has_internal_problem or used_external, (
        "OpenAPI must define Problem schema internally or reference an external schemas/Problem.schema.json."
    )
