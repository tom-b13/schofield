"""Architectural tests for EPIC C — Document Ingestion and Parsing.

These are static, file/AST-based checks designed to enforce contract-level
architecture before implementation exists. Each test maps 1:1 to a section
in 7.1 of the EPIC C spec and asserts only the requirements listed there.

Runner stability: these tests avoid executing application code and only read
files under the project root. Any parsing errors are caught and surfaced as
assertions rather than causing crashes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = PROJECT_ROOT / "schemas"


def _load_json(path: Path) -> Dict[str, Any]:
    """Load JSON from path, failing the test with a clear message on error."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        pytest.fail(f"Expected file is missing: {path}")
    except Exception as exc:  # pragma: no cover - defensive
        pytest.fail(f"Failed to read {path}: {exc}")

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        pytest.fail(f"Invalid JSON in {path}: {exc}")


def _has_type(schema: Dict[str, Any], expected: str) -> bool:
    """Return True if schema's `type` equals or includes `expected`.

    Supports JSON Schema where `type` may be a string or a list of strings.
    """
    t = schema.get("type")
    if isinstance(t, str):
        return t == expected
    if isinstance(t, list):
        return expected in t
    return False


def _get_prop(schema: Dict[str, Any], *path: str) -> Dict[str, Any]:
    """Navigate nested properties definitions.

    Example: _get_prop(schema, "document", "order_number") returns the
    property-schema for `document.properties.order_number`.
    Fails with a clear assertion if any level is missing.
    """
    current = schema
    if not path:
        return current
    # First hop: top-level properties
    props = current.get("properties")
    if not isinstance(props, dict):
        pytest.fail("Schema has no top-level 'properties' object where expected.")
    key = path[0]
    if key not in props:
        pytest.fail(f"Missing property '{key}' in schema properties.")
    current = props[key]
    # For remaining hops, each hop expects a nested object's properties
    for key in path[1:]:
        if not isinstance(current, dict):
            pytest.fail("Encountered non-object while traversing schema properties.")
        nested_props = current.get("properties")
        if not isinstance(nested_props, dict):
            pytest.fail(
                f"Property '{key}' expected under an object with 'properties'."
            )
        if key not in nested_props:
            pytest.fail(f"Missing nested property '{key}' in schema properties.")
        current = nested_props[key]
    if not isinstance(current, dict):
        pytest.fail("Resolved property is not a schema object.")
    return current


def _iter_schema_files(root: Path, patterns: Iterable[str]) -> Iterable[Path]:
    """Yield files in `root` matching any filename regex in `patterns`."""
    compiled = [re.compile(p) for p in patterns]
    if not root.exists():
        return []  # type: ignore[return-value]
    for path in root.rglob("*.schema.json"):
        name = path.name
        if any(r.search(name) for r in compiled):
            yield path


# 7.1.1 — Document schema declares required fields
def test_7_1_1_document_schema_declares_required_fields() -> None:
    """Asserts Document schema exposes required fields and types per 7.1.1."""
    # Verifies section 7.1.1
    schema_path = SCHEMAS_DIR / "Document.schema.json"
    assert schema_path.exists(), "schemas/Document.schema.json must exist."
    schema = _load_json(schema_path)

    # Assert: properties id, title, order_number, version, created_at, updated_at exist
    for prop in ("id", "title", "order_number", "version", "created_at", "updated_at"):
        _ = _get_prop(schema, prop)

    # Assert: title: string; order_number: integer; version: integer
    assert _has_type(_get_prop(schema, "title"), "string"), "title must be type string."
    assert _has_type(_get_prop(schema, "order_number"), "integer"), "order_number must be type integer."
    assert _has_type(_get_prop(schema, "version"), "integer"), "version must be type integer."


# 7.1.2 — DocumentBlob schema declares required fields
def test_7_1_2_documentblob_schema_declares_required_fields() -> None:
    """Validates DocumentBlob schema required fields and types per 7.1.2."""
    # Verifies section 7.1.2
    schema_path = SCHEMAS_DIR / "DocumentBlob.schema.json"
    assert schema_path.exists(), "schemas/DocumentBlob.schema.json must exist."
    schema = _load_json(schema_path)

    # Assert: properties file_sha256, filename, mime, byte_size, storage_url exist
    for prop in ("file_sha256", "filename", "mime", "byte_size", "storage_url"):
        _ = _get_prop(schema, prop)

    # Assert: declared types
    assert _has_type(_get_prop(schema, "file_sha256"), "string"), "file_sha256 must be type string."
    assert _has_type(_get_prop(schema, "filename"), "string"), "filename must be type string."
    assert _has_type(_get_prop(schema, "mime"), "string"), "mime must be type string."
    assert _has_type(_get_prop(schema, "byte_size"), "integer"), "byte_size must be type integer."
    assert _has_type(_get_prop(schema, "storage_url"), "string"), "storage_url must be type string."


# 7.1.3 — No diffs/revision schema present
def test_7_1_3_no_diffs_or_revision_schema_present() -> None:
    """Fails if any diff/revision schema is present per 7.1.3."""
    # Verifies section 7.1.3
    assert SCHEMAS_DIR.exists(), "schemas/ directory must exist."

    # Assert: No specific file exists
    forbidden = SCHEMAS_DIR / "DocumentRevision.schema.json"
    assert not forbidden.exists(), "Forbidden schema must not exist: DocumentRevision.schema.json"

    # Assert: No file matches regex ^Document(Diff|Delta|Change|Revision).schema.json$
    pattern = re.compile(r"^Document(Diff|Delta|Change|Revision)\.schema\.json$")
    offenders = [p for p in SCHEMAS_DIR.rglob("*.schema.json") if pattern.match(p.name)]
    assert not offenders, (
        "Forbidden diff/revision schemas found: " + ", ".join(p.name for p in offenders)
    )


# 7.1.4 — Output schema separation – document response schema present
def test_7_1_4_document_response_schema_present() -> None:
    """Ensures DocumentResponse schema exists and exposes document with required fields per 7.1.4."""
    # Verifies section 7.1.4
    schema_path = SCHEMAS_DIR / "DocumentResponse.schema.json"
    assert schema_path.exists(), "schemas/DocumentResponse.schema.json must exist."
    schema = _load_json(schema_path)

    # Assert: top-level property `document`
    _get_prop(schema, "document")

    # Assert: document object declares properties document_id, title, order_number, version
    for prop in ("document_id", "title", "order_number", "version"):
        _ = _get_prop(schema, "document", prop)


# 7.1.5 — Output schema separation – list response schema present
def test_7_1_5_list_response_schema_present() -> None:
    """Validates list response schema presence, list_etag, and item fields per 7.1.5."""
    # Verifies section 7.1.5
    schema_path = SCHEMAS_DIR / "DocumentListResponse.schema.json"
    assert schema_path.exists(), "schemas/DocumentListResponse.schema.json must exist."
    schema = _load_json(schema_path)

    # Assert: top-level properties list and list_etag
    _ = _get_prop(schema, "list")
    _ = _get_prop(schema, "list_etag")

    # Assert: list is an array and items declare document_id, title, order_number, version
    list_prop = _get_prop(schema, "list")
    assert _has_type(list_prop, "array"), "'list' must be of type array."
    items = list_prop.get("items")
    if not isinstance(items, dict):
        pytest.fail("'list.items' must be a schema object.")
    # Check item properties
    for prop in ("document_id", "title", "order_number", "version"):
        # Navigate within items' properties
        if "properties" not in items or prop not in items["properties"]:
            pytest.fail(f"'list.items' must declare property '{prop}'.")


# 7.1.6 — Output schema separation – content update result schema present
def test_7_1_6_content_update_result_schema_present() -> None:
    """Checks ContentUpdateResult schema exposes content_result with document_id and version per 7.1.6."""
    # Verifies section 7.1.6
    schema_path = SCHEMAS_DIR / "ContentUpdateResult.schema.json"
    assert schema_path.exists(), "schemas/ContentUpdateResult.schema.json must exist."
    schema = _load_json(schema_path)

    # Assert: top-level property content_result with properties document_id and version
    _ = _get_prop(schema, "content_result")
    for prop in ("document_id", "version"):
        _ = _get_prop(schema, "content_result", prop)


# 7.1.7 — Output schema separation – blob metadata projection schema present
def test_7_1_7_blob_metadata_projection_schema_present() -> None:
    """Ensures BlobMetadataProjection schema exists and exposes required blob fields per 7.1.7."""
    # Verifies section 7.1.7
    schema_path = SCHEMAS_DIR / "BlobMetadataProjection.schema.json"
    assert schema_path.exists(), "schemas/BlobMetadataProjection.schema.json must exist."
    schema = _load_json(schema_path)

    # Assert: top-level property blob_metadata with required subproperties
    _ = _get_prop(schema, "blob_metadata")
    for prop in ("file_sha256", "filename", "mime", "byte_size", "storage_url"):
        _ = _get_prop(schema, "blob_metadata", prop)


# 7.1.8 — ETag support fields available in list response schema
def test_7_1_8_etag_present_in_list_response_schema() -> None:
    """Asserts list_etag exists and is type string per 7.1.8."""
    # Verifies section 7.1.8
    schema_path = SCHEMAS_DIR / "DocumentListResponse.schema.json"
    assert schema_path.exists(), "schemas/DocumentListResponse.schema.json must exist."
    schema = _load_json(schema_path)

    # Assert: list_etag exists and is type string at top-level
    list_etag = _get_prop(schema, "list_etag")
    assert _has_type(list_etag, "string"), "'list_etag' must be type string."


# 7.1.9 — Title field constraints are declared
def test_7_1_9_title_field_constraints_declared() -> None:
    """Validates title field type and non-empty constraint per 7.1.9."""
    # Verifies section 7.1.9
    schema_path = SCHEMAS_DIR / "Document.schema.json"
    assert schema_path.exists(), "schemas/Document.schema.json must exist."
    schema = _load_json(schema_path)

    # Assert: title exists and is type string
    title_schema = _get_prop(schema, "title")
    assert _has_type(title_schema, "string"), "title must be type string."

    # Assert: Non-empty constraint (minLength >= 1)
    min_len = title_schema.get("minLength")
    assert isinstance(min_len, int) and min_len >= 1, "title must enforce minLength >= 1."


# 7.1.10 — Unique sequential ordering is represented at the contract layer
def test_7_1_10_order_number_present_and_typed_across_schemas() -> None:
    """Ensures order_number is present and typed integer across relevant schemas per 7.1.10."""
    # Verifies section 7.1.10
    # Document.schema.json
    doc_schema_path = SCHEMAS_DIR / "Document.schema.json"
    assert doc_schema_path.exists(), "schemas/Document.schema.json must exist."
    doc_schema = _load_json(doc_schema_path)
    assert _has_type(_get_prop(doc_schema, "order_number"), "integer"), (
        "Document.schema.json: 'order_number' must be type integer."
    )

    # DocumentListResponse.schema.json (items)
    list_schema_path = SCHEMAS_DIR / "DocumentListResponse.schema.json"
    assert list_schema_path.exists(), "schemas/DocumentListResponse.schema.json must exist."
    list_schema = _load_json(list_schema_path)
    list_prop = _get_prop(list_schema, "list")
    assert _has_type(list_prop, "array"), "'list' must be of type array."
    items = list_prop.get("items")
    if not isinstance(items, dict):
        pytest.fail("'list.items' must be a schema object.")
    item_order = items.get("properties", {}).get("order_number")
    if not isinstance(item_order, dict):
        pytest.fail("'list.items' must declare property 'order_number'.")
    assert _has_type(item_order, "integer"), (
        "DocumentListResponse.schema.json: 'order_number' in items must be type integer."
    )

    # DocumentResponse.schema.json (document object)
    resp_schema_path = SCHEMAS_DIR / "DocumentResponse.schema.json"
    assert resp_schema_path.exists(), "schemas/DocumentResponse.schema.json must exist."
    resp_schema = _load_json(resp_schema_path)
    assert _has_type(_get_prop(resp_schema, "document", "order_number"), "integer"), (
        "DocumentResponse.schema.json: 'document.order_number' must be type integer."
    )


# 7.1.11 — Version field present in schemas that expose document state
def test_7_1_11_version_field_present_across_schemas() -> None:
    """Ensures version is present and typed integer across schemas per 7.1.11."""
    # Verifies section 7.1.11
    # Document.schema.json
    doc_schema = _load_json(SCHEMAS_DIR / "Document.schema.json")
    assert _has_type(_get_prop(doc_schema, "version"), "integer"), (
        "Document.schema.json: 'version' must be type integer."
    )

    # DocumentResponse.schema.json (document object)
    resp_schema = _load_json(SCHEMAS_DIR / "DocumentResponse.schema.json")
    assert _has_type(_get_prop(resp_schema, "document", "version"), "integer"), (
        "DocumentResponse.schema.json: 'document.version' must be type integer."
    )

    # DocumentListResponse.schema.json (items)
    list_schema = _load_json(SCHEMAS_DIR / "DocumentListResponse.schema.json")
    list_prop = _get_prop(list_schema, "list")
    assert _has_type(list_prop, "array"), "'list' must be of type array."
    items = list_prop.get("items")
    if not isinstance(items, dict):
        pytest.fail("'list.items' must be a schema object.")
    item_version = items.get("properties", {}).get("version")
    if not isinstance(item_version, dict):
        pytest.fail("'list.items' must declare property 'version'.")
    assert _has_type(item_version, "integer"), (
        "DocumentListResponse.schema.json: 'version' in items must be type integer."
    )

    # ContentUpdateResult.schema.json (content_result)
    cur_schema = _load_json(SCHEMAS_DIR / "ContentUpdateResult.schema.json")
    assert _has_type(_get_prop(cur_schema, "content_result", "version"), "integer"), (
        "ContentUpdateResult.schema.json: 'content_result.version' must be type integer."
    )


# 7.1.12 — Absence of PATCH order_number in response schemas
def test_7_1_12_absence_of_patch_order_number_in_response_schemas() -> None:
    """Asserts order_number is read-only in responses and not present in any PATCH-like request schema per 7.1.12."""
    # Verifies section 7.1.12
    # Ensure order_number is read-only in the response schema
    resp_schema = _load_json(SCHEMAS_DIR / "DocumentResponse.schema.json")
    order_schema = _get_prop(resp_schema, "document", "order_number")
    assert order_schema.get("readOnly") is True, (
        "DocumentResponse.schema.json: 'document.order_number' must be marked readOnly:true."
    )

    # If any PATCH-like request schema exists, ensure it does NOT expose 'order_number'
    candidate_files = list(
        _iter_schema_files(
            SCHEMAS_DIR,
            patterns=[
                r"Patch\.schema\.json$",
                r"Update\w*\.schema\.json$",
                r"DocumentPatch\w*\.schema\.json$",
                r"DocumentMetadata(Update|Patch)\w*\.schema\.json$",
                r"Document(Update|Request)\w*\.schema\.json$",
            ],
        )
    )

    def contains_order_number(schema_obj: Dict[str, Any]) -> bool:
        # Traverse schema to find any 'properties' dicts containing 'order_number'.
        stack = [schema_obj]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                props = node.get("properties")
                if isinstance(props, dict) and "order_number" in props:
                    return True
                for v in node.values():
                    stack.append(v)
            elif isinstance(node, list):
                stack.extend(node)
        return False

    for file in candidate_files:
        schema = _load_json(file)
        assert not contains_order_number(schema), (
            f"'{file.name}' must not expose 'order_number' as a writable property."
        )


def _walk(obj: Any) -> Iterable[Any]:
    """Yield all nested values from a JSON-like structure (dicts/lists/primitives)."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


def _extract_problem_refs_from_openapi_yaml(yaml_text: str) -> list[str]:
    """Extract $ref targets under application/problem+json content blocks.

    Minimal indentation-aware scan to avoid brittle substring checks. This parser
    is intentionally narrow: it only tracks when we're within a mapping keyed by
    'application/problem+json:' and collects any '$ref: ...' lines nested under it.
    """
    refs: list[str] = []
    in_problem_block = False
    problem_indent = None
    for raw in yaml_text.splitlines():
        line = raw.rstrip("\n\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        # Enter problem+json block
        if re.match(r"^\s*application/problem\+json\s*:\s*$", line):
            in_problem_block = True
            problem_indent = indent
            continue
        # Leave block when indentation decreases to or above the block's indent
        if in_problem_block and problem_indent is not None and indent <= problem_indent:
            in_problem_block = False
            problem_indent = None
        if in_problem_block:
            m = re.match(r"^\s*\$ref\s*:\s*(.+)\s*$", line)
            if m:
                # Strip quotes if present
                val = m.group(1).strip().strip('"').strip("'")
                refs.append(val)
    return refs


# 7.1.13 — Problem+json error media type is declared at contract level
def test_7_1_13_problem_json_contract_declared() -> None:
    """Ensures a reusable Problem schema exists and is referenced by error responses (7.1.13)."""
    # Verifies section 7.1.13
    assert SCHEMAS_DIR.exists(), "schemas/ directory must exist."

    # 1) Assert schemas/Problem.schema.json exists and is a valid object schema
    problem_path = SCHEMAS_DIR / "Problem.schema.json"
    assert problem_path.exists(), "schemas/Problem.schema.json must exist."
    problem_schema = _load_json(problem_path)
    assert _has_type(problem_schema, "object"), "Problem schema must declare type: object."

    # 2) Evidence path A: At least one other JSON schema references Problem.schema.json via $ref
    problem_ref_pattern = re.compile(r"Problem\.schema\.json(?:[#\"'].*)?$")
    schema_ref_found = False
    for path in SCHEMAS_DIR.rglob("*.json"):
        if path.resolve() == problem_path.resolve():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in _walk(data):
            if isinstance(node, dict) and "$ref" in node and isinstance(node["$ref"], str):
                if problem_ref_pattern.search(node["$ref"]):
                    schema_ref_found = True
                    break
        if schema_ref_found:
            break

    # 3) Evidence path B: OpenAPI declares application/problem+json content linked to Problem component
    openapi_ok = False
    openapi_path = PROJECT_ROOT / "docs" / "api" / "openapi.yaml"
    if openapi_path.exists():
        try:
            yaml_text = openapi_path.read_text(encoding="utf-8")
        except Exception as exc:  # pragma: no cover - defensive
            pytest.fail(f"Failed to read OpenAPI file: {exc}")
        refs = _extract_problem_refs_from_openapi_yaml(yaml_text)
        # Require that at least one such $ref targets the Problem component specifically
        openapi_ok = any(re.search(r"#/components/schemas/Problem$", r) for r in refs)

    # 4) Either/or acceptance per spec 7.1.13
    assert (schema_ref_found or openapi_ok), (
        "Expected either: (a) at least one JSON schema under 'schemas/' $ref's Problem.schema.json, "
        "or (b) docs/api/openapi.yaml declares an application/problem+json content with schema $ref to '#/components/schemas/Problem'."
    )
