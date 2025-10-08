"""Architectural tests for Epic D — Bindings and transforms (section 7.1).

These tests statically validate architectural constraints before implementation
exists. Each test maps 1:1 to a 7.1.x section and asserts only the listed
requirements. Tests avoid executing application code; they rely on filesystem
inspection and Python AST parsing. Any parsing errors fail tests with clear
messages rather than crashing the suite.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_ROUTES_DIR = PROJECT_ROOT / "app" / "routes"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        pytest.fail(f"Expected file is missing: {path}")
    except Exception as exc:  # pragma: no cover - defensive
        pytest.fail(f"Failed to read {path}: {exc}")


def _load_json(path: Path) -> Dict[str, Any]:
    raw = _read_text(path)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        pytest.fail(f"Invalid JSON in {path}: {exc}")


def _has_type(schema: Dict[str, Any], expected: str) -> bool:
    t = schema.get("type")
    if isinstance(t, str):
        return t == expected
    if isinstance(t, list):
        return expected in t
    return False


def _get_prop(schema: Dict[str, Any], *path: str) -> Dict[str, Any]:
    current = schema
    if not path:
        return current
    props = current.get("properties")
    if not isinstance(props, dict):
        pytest.fail("Schema has no top-level 'properties' where expected.")
    key = path[0]
    if key not in props:
        pytest.fail(f"Missing property '{key}' in schema properties.")
    current = props[key]
    for key in path[1:]:
        if not isinstance(current, dict):
            pytest.fail("Encountered non-object when traversing schema properties.")
        nested_props = current.get("properties")
        if not isinstance(nested_props, dict):
            pytest.fail(f"Property '{key}' expected under an object with 'properties'.")
        if key not in nested_props:
            pytest.fail(f"Missing nested property '{key}' in schema properties.")
        current = nested_props[key]
    if not isinstance(current, dict):
        pytest.fail("Resolved property is not a schema object.")
    return current


@dataclass
class RouteDef:
    file: Path
    method: str
    path: str


def _iter_route_files() -> List[Path]:
    if not APP_ROUTES_DIR.exists():
        return []
    return [p for p in APP_ROUTES_DIR.glob("*.py") if p.name != "__init__.py"]


def _extract_routes_from_file(path: Path) -> List[RouteDef]:
    src = _read_text(path)
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        pytest.fail(f"Failed to parse {path}: {exc}")

    routes: List[RouteDef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr = node.func.attr
            if attr in {"get", "post", "put", "patch", "delete"}:
                # only consider calls on a name 'router' or attribute ending with '.router'
                owner = node.func.value
                owner_ok = False
                if isinstance(owner, ast.Name) and owner.id == "router":
                    owner_ok = True
                elif isinstance(owner, ast.Attribute) and owner.attr == "router":
                    owner_ok = True
                if not owner_ok:
                    continue
                if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    path_str = node.args[0].value
                    routes.append(RouteDef(file=path, method=attr.upper(), path=path_str))
    return routes


def _find_route_functions(module_path: Path, route_path: str) -> List[ast.FunctionDef]:
    """Return function defs decorated with router.<method>(route_path).

    Pure AST inspection; raises a pytest failure on parse errors.
    """
    src = _read_text(module_path)
    try:
        tree = ast.parse(src, filename=str(module_path))
    except SyntaxError as exc:  # pragma: no cover - defensive
        pytest.fail(f"Failed to parse {module_path}: {exc}")

    func_defs: List[ast.FunctionDef] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    if dec.func.attr in {"get", "post", "put", "patch", "delete"}:
                        if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                            if dec.args[0].value == route_path:
                                func_defs.append(node)
    return func_defs


def _module_name_from_path(path: Path) -> str:
    """Convert a file path under project root into a dotted module name."""
    rel = path.resolve().relative_to(PROJECT_ROOT)
    mod = ".".join(rel.with_suffix("").parts)
    return mod


def _collect_routes() -> List[RouteDef]:
    routes: List[RouteDef] = []
    for f in _iter_route_files():
        routes.extend(_extract_routes_from_file(f))
    return routes


def _route_index_by_path() -> Dict[str, List[RouteDef]]:
    idx: Dict[str, List[RouteDef]] = {}
    for r in _collect_routes():
        idx.setdefault(r.path, []).append(r)
    return idx


def _list_top_level_imports(path: Path) -> Set[str]:
    """Return a set of imported module names from the file's top-level imports.

    Only static imports are considered (import X / from X import Y). Does not
    execute any code.
    """
    src = _read_text(path)
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError as exc:
        pytest.fail(f"Failed to parse {path}: {exc}")

    modules: Set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name:
                    modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
    return modules


def _has_persistence_import(imports: Set[str]) -> bool:
    patterns = [
        r"(^|\.)sqlalchemy(\.|$)",
        r"(^|\.)psycopg2(\.|$)",
        r"(^|\.)alembic(\.|$)",
        r"(^|\.)app\.db(\.|$)",
        r"(^|\.)app\.logic\.repository_",
        r"(^|\.)app\.logic\.repository(\.|$)",
        r"(^|\.)app\.logic\.migrations(\.|$)",
    ]
    for mod in imports:
        for pat in patterns:
            if re.search(pat, mod):
                return True
    return False


# 7.1.1 — Distinct modules for suggestion and binding
def test_7_1_1_distinct_modules_for_suggest_and_bind() -> None:
    """Asserts suggest and bind live in distinct route modules."""
    # Verifies section 7.1.1
    # Assert: routes for suggest and bind exist and originate from different modules
    routes_by_path = _route_index_by_path()
    suggest_defs = routes_by_path.get("/transforms/suggest", [])
    bind_defs = routes_by_path.get("/placeholders/bind", [])

    assert suggest_defs, "Router must contain handler for '/transforms/suggest'."
    assert bind_defs, "Router must contain handler for '/placeholders/bind'."

    # Use first occurrence for origin comparison
    suggest_file = suggest_defs[0].file
    bind_file = bind_defs[0].file
    assert suggest_file != bind_file, (
        "Suggest and bind handlers must be defined in distinct modules."
    )


# 7.1.2 — Suggest endpoint has no persistence imports (stateless)
def test_7_1_2_suggest_endpoint_has_no_persistence_imports() -> None:
    """Asserts suggest handler module has no persistence imports."""
    # Verifies section 7.1.2
    routes_by_path = _route_index_by_path()
    suggest_defs = routes_by_path.get("/transforms/suggest", [])
    assert suggest_defs, "Suggest handler not found; expected '/transforms/suggest'."
    suggest_file = suggest_defs[0].file
    imports = _list_top_level_imports(suggest_file)
    assert not _has_persistence_import(imports), (
        "Suggestion handler module must not import persistence/ORM/DB layers."
    )


# 7.1.3 — Preview endpoint has no persistence imports (isolation)
def test_7_1_3_preview_endpoint_is_isolated_from_persistence() -> None:
    """Asserts preview handler module has no persistence imports."""
    # Verifies section 7.1.3
    routes_by_path = _route_index_by_path()
    preview_defs = routes_by_path.get("/transforms/preview", [])
    assert preview_defs, "Preview handler not found; expected '/transforms/preview'."
    preview_file = preview_defs[0].file
    imports = _list_top_level_imports(preview_file)
    assert not _has_persistence_import(imports), (
        "Preview handler module must not import persistence/ORM/DB layers."
    )


# 7.1.4 — Bind and unbind handlers require concurrency & idempotency headers
def test_7_1_4_headers_schema_and_validator_wiring() -> None:
    """Asserts bind/unbind route decorators wire idempotency and ETag headers."""
    # Verifies section 7.1.4
    headers_path = SCHEMAS_DIR / "HttpHeaders.json"
    assert headers_path.exists(), "schemas/HttpHeaders.json must exist."
    headers = _load_json(headers_path)
    # Assert schema defines Idempotency-Key and If-Match
    props = headers.get("properties") or {}
    assert "Idempotency-Key" in props, "HttpHeaders.json must define 'Idempotency-Key'."
    assert "If-Match" in props, "HttpHeaders.json must define 'If-Match'."
    # Assert headers are marked required by the schema
    required_keys = set(headers.get("required", []))
    assert {"Idempotency-Key", "If-Match"}.issubset(required_keys), (
        "HttpHeaders.json must mark both 'Idempotency-Key' and 'If-Match' as required"
    )

    # Validator wiring via AST of route decorators
    routes_by_path = _route_index_by_path()
    bind_defs = routes_by_path.get("/placeholders/bind", [])
    unbind_defs = routes_by_path.get("/placeholders/unbind", [])
    assert bind_defs, "Bind handler not found; expected '/placeholders/bind'."
    assert unbind_defs, "Unbind handler not found; expected '/placeholders/unbind'."
    # Extract the specific route function definitions
    bind_funcs = _find_route_functions(bind_defs[0].file, "/placeholders/bind")
    unbind_funcs = _find_route_functions(unbind_defs[0].file, "/placeholders/unbind")
    assert bind_funcs, "Could not locate bind route function via decorator AST."
    assert unbind_funcs, "Could not locate unbind route function via decorator AST."

    def _decorator_contains_header_refs(fn: ast.FunctionDef, want_idem: bool, want_if_match: bool) -> bool:
        found_idem = False
        found_ifm = False
        for dec in fn.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            # Inspect args/keywords for names/strings referencing header validators/constants
            nodes: List[ast.AST] = list(dec.args) + [kw.value for kw in dec.keywords]
            for n in nodes:
                for sub in ast.walk(n):
                    if isinstance(sub, ast.Name):
                        ident = sub.id.lower()
                        if "idempotency" in ident:
                            found_idem = True
                        if "if_match" in ident or "ifmatch" in ident:
                            found_ifm = True
                        if "httpheaders" in ident:
                            # single constant implying both
                            found_idem = found_idem or want_idem
                            found_ifm = found_ifm or want_if_match
                    elif isinstance(sub, ast.Attribute):
                        attr = sub.attr.lower()
                        if "idempotency" in attr:
                            found_idem = True
                        if "if_match" in attr or "ifmatch" in attr:
                            found_ifm = True
                    elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        sval = sub.value.lower()
                        if "idempotency-key" in sval:
                            found_idem = True
                        if "if-match" in sval:
                            found_ifm = True
        return (not want_idem or found_idem) and (not want_if_match or found_ifm)

    assert _decorator_contains_header_refs(bind_funcs[0], want_idem=True, want_if_match=True), (
        "Bind route decorator should reference validators/constants for Idempotency-Key and If-Match"
    )
    assert _decorator_contains_header_refs(unbind_funcs[0], want_idem=False, want_if_match=True), (
        "Unbind route decorator should reference validators/constants for If-Match"
    )

    # Strengthen: ensure the bind decorator explicitly wires a headers validator via a keyword
    def _decorator_has_headers_validator_keyword(fn: ast.FunctionDef) -> bool:
        for dec in fn.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            # Only consider HTTP method decorators
            if dec.func.attr not in {"get", "post", "put", "patch", "delete"}:
                continue
            # Expect at least one keyword argument referencing headers schema/validator
            for kw in dec.keywords:
                if kw.value is None:
                    continue
                for sub in ast.walk(kw.value):
                    if isinstance(sub, ast.Name) and sub.id.lower() in {"httpheaders", "headers", "headers_validator"}:
                        return True
                    if isinstance(sub, ast.Attribute) and (
                        sub.attr.lower() in {"httpheaders", "headers", "headers_validator"}
                    ):
                        return True
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        sval = sub.value.lower()
                        if any(tok in sval for tok in ("httpheaders.json", "idempotency-key", "if-match")):
                            return True
        return False

    assert _decorator_has_headers_validator_keyword(bind_funcs[0]), (
        "Bind route should explicitly wire a headers validator (e.g., via a keyword referencing HttpHeaders)"
    )

    # Strengthen: unbind must explicitly reference If-Match in decorator keywords (required)
    def _decorator_keywords_contain_if_match_required(fn: ast.FunctionDef) -> bool:
        for dec in fn.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            for kw in dec.keywords:
                for sub in ast.walk(kw.value):
                    if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and "if-match" in sub.value.lower():
                        return True
                    if isinstance(sub, ast.Name) and ("if_match" in sub.id.lower() or "ifmatch" in sub.id.lower()):
                        return True
                    if isinstance(sub, ast.Attribute) and ("if_match" in sub.attr.lower() or "ifmatch" in sub.attr.lower()):
                        return True
        return False

    assert _decorator_keywords_contain_if_match_required(unbind_funcs[0]), (
        "Unbind route should explicitly require If-Match via decorator keyword wiring"
    )


# 7.1.5 — PlaceholderProbe schema is reused by suggest and bind
def test_7_1_5_placeholderprobe_reused_by_suggest_and_bind() -> None:
    """Asserts PlaceholderProbe schema is referenced by suggest and bind."""
    # Verifies section 7.1.5
    probe_path = SCHEMAS_DIR / "PlaceholderProbe.json"
    assert probe_path.exists(), "schemas/PlaceholderProbe.json must exist."
    routes_by_path = _route_index_by_path()
    suggest_defs = routes_by_path.get("/transforms/suggest", [])
    bind_defs = routes_by_path.get("/placeholders/bind", [])
    assert suggest_defs, "Suggest handler not found; expected '/transforms/suggest'."
    assert bind_defs, "Bind handler not found; expected '/placeholders/bind'."
    suggest_src = _read_text(suggest_defs[0].file)
    bind_src = _read_text(bind_defs[0].file)
    assert "PlaceholderProbe.json" in suggest_src, (
        "Suggest handler should reference schemas/PlaceholderProbe.json"
    )
    # Bind may reference ProbeReceipt or PlaceholderProbe; allow either as per spec
    assert ("PlaceholderProbe.json" in bind_src) or ("ProbeReceipt.json" in bind_src), (
        "Bind handler should reference PlaceholderProbe or ProbeReceipt schema"
    )


# 7.1.6 — ProbeReceipt schema present and referenced
def test_7_1_6_probereceipt_schema_present_and_referenced() -> None:
    """Asserts ProbeReceipt schema exists and is referenced by suggest and bind."""
    # Verifies section 7.1.6
    probe_receipt = SCHEMAS_DIR / "ProbeReceipt.json"
    suggest_resp = SCHEMAS_DIR / "SuggestResponse.json"
    assert probe_receipt.exists(), "schemas/ProbeReceipt.json must exist."
    assert suggest_resp.exists(), "schemas/SuggestResponse.json must exist."
    resp_schema = _load_json(suggest_resp)
    probe_prop = _get_prop(resp_schema, "probe")
    ref = probe_prop.get("$ref")
    assert isinstance(ref, str) and ref.endswith("ProbeReceipt.json"), (
        "SuggestResponse.probe must $ref ProbeReceipt.json"
    )

    # Bind references ProbeReceipt in request or validator wiring
    routes_by_path = _route_index_by_path()
    bind_defs = routes_by_path.get("/placeholders/bind", [])
    assert bind_defs, "Bind handler not found; expected '/placeholders/bind'."
    bind_mod = bind_defs[0].file
    # Prefer AST-level presence to avoid comment false-positives
    src = _read_text(bind_mod)
    try:
        tree = ast.parse(src, filename=str(bind_mod))
    except SyntaxError as exc:  # pragma: no cover - defensive
        pytest.fail(f"Failed to parse {bind_mod}: {exc}")
    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id.lower().startswith("probereceipt"):
            found = True
            break
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "ProbeReceipt.json" in node.value:
            found = True
            break
    assert found, "Bind handler should reference ProbeReceipt schema via symbol or $ref"


# 7.1.7 — TransformSuggestion schema defines answer_kind and options
def test_7_1_7_transformsuggestion_schema_has_kind_and_options() -> None:
    """Asserts TransformSuggestion schema defines answer_kind and options list."""
    # Verifies section 7.1.7
    path = SCHEMAS_DIR / "TransformSuggestion.json"
    assert path.exists(), "schemas/TransformSuggestion.json must exist."
    schema = _load_json(path)
    # answer_kind property exists and uses AnswerKind enum (ref or inline enum)
    ak = _get_prop(schema, "answer_kind")
    ak_ref = ak.get("$ref")
    ak_enum = ak.get("enum")
    assert (isinstance(ak_ref, str) and "AnswerKind.json" in ak_ref) or isinstance(ak_enum, list), (
        "answer_kind must $ref AnswerKind.json or declare an inline enum"
    )
    # options property present, array of OptionSpec
    options = _get_prop(schema, "options")
    assert _has_type(options, "array"), "options must be an array"
    items = options.get("items", {})
    assert isinstance(items, dict) and (
        ("$ref" in items and str(items["$ref"]).endswith("OptionSpec.json"))
    ), "options.items must $ref OptionSpec.json"


# 7.1.8 — AnswerKind enumeration contains all supported kinds
def test_7_1_8_answerkind_contains_all_supported_kinds() -> None:
    """Asserts AnswerKind enum contains the required kinds."""
    # Verifies section 7.1.8
    path = SCHEMAS_DIR / "AnswerKind.json"
    assert path.exists(), "schemas/AnswerKind.json must exist."
    schema = _load_json(path)
    enum = schema.get("enum")
    assert isinstance(enum, list), "AnswerKind.json must declare an enum array"
    expected = {"short_string", "long_text", "boolean", "number", "enum_single"}
    assert set(enum) == expected, (
        f"AnswerKind enum must equal {sorted(expected)}; found {sorted(enum)}"
    )


# 7.1.9 — OptionSpec enforces canonical value form
def test_7_1_9_optionspec_enforces_canonical_value_form() -> None:
    """Asserts OptionSpec.value enforces uppercase snake-case via pattern.""" 
    # Verifies section 7.1.9
    path = SCHEMAS_DIR / "OptionSpec.json"
    assert path.exists(), "schemas/OptionSpec.json must exist."
    schema = _load_json(path)
    value = _get_prop(schema, "value")
    assert _has_type(value, "string"), "OptionSpec.value must be type string"
    # Accept either pattern or a documented equivalent constraint
    pattern = value.get("pattern")
    assert isinstance(pattern, str) and pattern, (
        "OptionSpec.value should include a regex 'pattern' enforcing canonical form"
    )
    # Require anchored pattern and compatibility with uppercase snake-case
    p = pattern.strip()
    assert p.startswith("^") and p.endswith("$"), (
        "OptionSpec.value pattern must be anchored with ^ and $"
    )
    core = p[1:-1]
    # Semantic validation: compile and assert canonical examples
    rx = re.compile(p)
    assert rx.fullmatch("FOO") and rx.fullmatch("FOO_BAR1"), (
        "OptionSpec.value pattern should accept canonical uppercase snake-case values"
    )
    assert not rx.fullmatch("foo") and not rx.fullmatch("A-B") and not rx.fullmatch("A B"), (
        "OptionSpec.value pattern must reject lowercase, hyphens, and spaces"
    )
    assert re.search(r"[A-Z_\[\]]", core), (
        "OptionSpec.value pattern must target uppercase/underscore character classes"
    )
    common_equivalents = {"[A-Z0-9_]+", "[A-Z_][A-Z0-9_]*"}
    # If not one of the common equivalents, still acceptable if it passes the compatibility checks above
    if core not in common_equivalents:
        # Ensure digits/underscore allowance is present somewhere in the expression
        assert re.search(r"0-9|_", core), (
            "OptionSpec.value pattern should allow digits and underscores (or equivalent)"
        )
    # Optional props
    label = _get_prop(schema, "label")
    assert _has_type(label, "string"), "OptionSpec.label must be a string (optional)"
    _ = _get_prop(schema, "placeholder_key")


# 7.1.10 — Stable ordering validation hook present in response path
def test_7_1_10_stable_option_ordering_hook_present() -> None:
    """Asserts suggest/preview functions enforce deterministic ordering of options."""
    # Verifies section 7.1.10
    routes_by_path = _route_index_by_path()
    for route in ("/transforms/suggest", "/transforms/preview"):
        defs = routes_by_path.get(route, [])
        assert defs, f"Handler not found for '{route}'."
        func_defs = _find_route_functions(defs[0].file, route)
        assert func_defs, f"Could not locate route function for '{route}'."
        fn = func_defs[0]
        has_sort = False
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                # sorted(options) or options.sort(...)
                if isinstance(node.func, ast.Name) and node.func.id == "sorted":
                    has_sort = True
                    break
                if isinstance(node.func, ast.Attribute) and node.func.attr == "sort":
                    has_sort = True
                    break
        assert has_sort, f"{route} must apply sorted()/list.sort() within the route function"


# 7.1.11 — ProblemDetails schema exists and is wired for all endpoints
def test_7_1_11_problem_details_schema_and_wiring() -> None:
    """Asserts ProblemDetails schema exists and error handlers emit problem+json."""
    # Verifies section 7.1.11
    pd_path = SCHEMAS_DIR / "ProblemDetails.json"
    assert pd_path.exists(), "schemas/ProblemDetails.json must exist."
    # Constrain to likely error-handling modules
    candidates = [
        *(PROJECT_ROOT / "app").rglob("*error*.py"),
        *(PROJECT_ROOT / "app").rglob("*exception*.py"),
        *(PROJECT_ROOT / "app").rglob("middleware*.py"),
        PROJECT_ROOT / "app" / "main.py",
    ]
    found_problem_json_ref = False
    found_content_type = False
    for py in candidates:
        if not py.exists():
            continue
        try:
            tree = ast.parse(_read_text(py), filename=str(py))
        except SyntaxError:
            # Fall back to raw scan if parse fails
            text = _read_text(py)
            if "ProblemDetails.json" in text:
                found_problem_json_ref = True
            if "application/problem+json" in text:
                found_content_type = True
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "application/problem+json" in node.value:
                found_content_type = True
            if isinstance(node, ast.ImportFrom) and node.module and "ProblemDetails" in node.module:
                found_problem_json_ref = True
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and "ProblemDetails.json" in node.value:
                found_problem_json_ref = True
    assert found_content_type, "Error middleware must emit application/problem+json responses"
    assert found_problem_json_ref, "Expected explicit ProblemDetails schema reference in error-handling modules"


# 7.1.12 — All referenced schemas reside under root schemas/
def test_7_1_12_all_referenced_schemas_exist_under_root() -> None:
    """Asserts all referenced schemas exist under the root schemas/ directory."""
    # Verifies section 7.1.12
    required = [
        "PlaceholderProbe.json",
        "ProbeReceipt.json",
        "TransformSuggestion.json",
        "OptionSpec.json",
        "AnswerKind.json",
        "SuggestResponse.json",
        "BindRequest.json",
        "BindResult.json",
        "UnbindResponse.json",
        "ListPlaceholdersResponse.json",
        "Placeholder.json",
        "Span.json",
        "TransformsCatalogResponse.json",
        "TransformsCatalogItem.json",
        "TransformsPreviewRequest.json",
        "TransformsPreviewResponse.json",
        "PurgeRequest.json",
        "PurgeResponse.json",
        "ProblemDetails.json",
        "HttpHeaders.json",
    ]
    missing = [name for name in required if not (SCHEMAS_DIR / name).exists()]
    assert not missing, f"Missing schema files under schemas/: {missing}"


# 7.1.13 — Purge request/response schemas present
def test_7_1_13_purge_request_and_response_schemas_present() -> None:
    """Asserts purge request/response schemas exist and have integer counters."""
    # Verifies section 7.1.13
    req = SCHEMAS_DIR / "PurgeRequest.json"
    resp = SCHEMAS_DIR / "PurgeResponse.json"
    assert req.exists(), "schemas/PurgeRequest.json must exist."
    assert resp.exists(), "schemas/PurgeResponse.json must exist."
    schema = _load_json(resp)
    deleted = _get_prop(schema, "deleted_placeholders")
    updated = _get_prop(schema, "updated_questions")
    assert _has_type(deleted, "integer"), "deleted_placeholders must be integer"
    assert _has_type(updated, "integer"), "updated_questions must be integer"


# 7.1.14 — Placeholders list item schema includes identifiers and timestamps
def test_7_1_14_placeholder_list_item_schema_fields() -> None:
    """Asserts Placeholder/ListPlaceholdersResponse fields and date-time format."""
    # Verifies section 7.1.14
    ph = SCHEMAS_DIR / "Placeholder.json"
    lresp = SCHEMAS_DIR / "ListPlaceholdersResponse.json"
    span = SCHEMAS_DIR / "Span.json"
    assert ph.exists(), "schemas/Placeholder.json must exist."
    assert lresp.exists(), "schemas/ListPlaceholdersResponse.json must exist."
    assert span.exists(), "schemas/Span.json must exist."
    ph_schema = _load_json(ph)
    # Required fields on Placeholder
    for prop in ("id", "document_id", "clause_path", "text_span", "question_id", "transform_id", "created_at"):
        _ = _get_prop(ph_schema, prop)
    # text_span ref check
    ts = _get_prop(ph_schema, "text_span")
    assert ts.get("$ref", "").endswith("Span.json"), "text_span must $ref Span.json"
    # created_at format
    created_at = _get_prop(ph_schema, "created_at")
    assert created_at.get("format") == "date-time", "created_at must have format: date-time"
    # List response references Placeholder
    l_schema = _load_json(lresp)
    items_schema = _get_prop(l_schema, "items")
    ref = (items_schema.get("items") or {}).get("$ref", "")
    assert ref.endswith("Placeholder.json"), (
        "ListPlaceholdersResponse.items must be an array of Placeholder via $ref"
    )


# 7.1.15 — Read vs write model separation (imports)
def test_7_1_15_read_vs_write_model_import_separation() -> None:
    """Asserts read and write route modules have strict import separation."""
    # Verifies section 7.1.15
    routes_by_path = _route_index_by_path()
    read_paths = [
        "/questions/{id}/placeholders",
        "/transforms/catalog",
        "/transforms/preview",
    ]
    write_paths = [
        "/placeholders/bind",
        "/placeholders/unbind",
        "/documents/{id}/bindings:purge",
    ]
    # Collect modules
    read_mods = []
    for p in read_paths:
        defs = routes_by_path.get(p, [])
        assert defs, f"Read handler not found; expected '{p}'."
        read_mods.append(defs[0].file)
    write_mods = []
    for p in write_paths:
        defs = routes_by_path.get(p, [])
        assert defs, f"Write handler not found; expected '{p}'."
        write_mods.append(defs[0].file)

    # Assert import separation
    read_imports = set().union(*(_list_top_level_imports(m) for m in read_mods))
    write_imports = set().union(*(_list_top_level_imports(m) for m in write_mods))
    assert not _has_persistence_import(read_imports), (
        "Read handler modules must not import write/persistence layers"
    )
    # No reverse import of read modules into write modules (compare fully-qualified modules)
    read_module_names = {_module_name_from_path(p) for p in read_mods}
    for mod in write_imports:
        if mod in read_module_names:
            pytest.fail("Write modules must not import from read modules (separation)")


# 7.1.16 — ETag regeneration function invoked after bind and unbind
def test_7_1_16_etag_regeneration_used_by_bind_and_unbind() -> None:
    """Asserts bind/unbind import and invoke an ETag regeneration utility."""
    # Verifies section 7.1.16 (static inspection)
    routes_by_path = _route_index_by_path()
    bind_defs = routes_by_path.get("/placeholders/bind", [])
    unbind_defs = routes_by_path.get("/placeholders/unbind", [])
    assert bind_defs and unbind_defs, "Bind and Unbind handlers must exist."
    for route, defs in ("/placeholders/bind", bind_defs), ("/placeholders/unbind", unbind_defs):
        path = defs[0].file
        src = _read_text(path)
        try:
            tree = ast.parse(src, filename=str(path))
        except SyntaxError as exc:  # pragma: no cover - defensive
            pytest.fail(f"Failed to parse {path}: {exc}")
        # Assert an import of an etag utility module
        imported_etag = False
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("etag"):
                imported_etag = True
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.endswith("etag"):
                        imported_etag = True
        assert imported_etag, f"{route} module must import an ETag utility module"
        # Assert a function call that looks like etag regeneration
        calls_etag = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = None
                if isinstance(fn, ast.Name):
                    name = fn.id
                elif isinstance(fn, ast.Attribute):
                    name = fn.attr
                if name and ("etag" in name.lower() or "regenerat" in name.lower()):
                    calls_etag = True
                    break
        assert calls_etag, f"{route} should invoke an ETag regeneration function after operation"


# 7.1.17 — Transform registry is static and used by catalog
def test_7_1_17_transform_registry_static_and_used_by_catalog() -> None:
    """Asserts a static transform registry is imported and referenced by catalog."""
    # Verifies section 7.1.17
    # Static registry module presence
    registry_candidates = list((PROJECT_ROOT / "app").rglob("transform_registry.py"))
    assert registry_candidates, "Expected a static transform registry module (e.g., transform_registry.py)"

    # Catalog handler imports and uses registry
    routes_by_path = _route_index_by_path()
    catalog_defs = routes_by_path.get("/transforms/catalog", [])
    assert catalog_defs, "Catalog handler not found; expected '/transforms/catalog'."
    catalog_path = catalog_defs[0].file
    src = _read_text(catalog_path)
    try:
        tree = ast.parse(src, filename=str(catalog_path))
    except SyntaxError as exc:
        pytest.fail(f"Failed to parse {catalog_path}: {exc}")
    imported = False
    used_symbol = False
    imported_names: Set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module and node.module.endswith("transform_registry"):
            imported = True
            for a in node.names:
                imported_names.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.endswith("transform_registry"):
                    imported = True
                    imported_names.add(a.asname or a.name.split(".")[-1])
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in imported_names:
            used_symbol = True
            break
    assert imported, "Catalog handler must import the static transform_registry"
    assert used_symbol, "Catalog handler must reference a symbol from transform_registry"


# 7.1.18 — Response schema validation middleware is enabled globally
def test_7_1_18_response_schema_validation_middleware_enabled() -> None:
    """Asserts response schema validation middleware is globally registered."""
    # Verifies section 7.1.18
    # Restrict to bootstrap file and assert concrete registration call
    main_py = PROJECT_ROOT / "app" / "main.py"
    assert main_py.exists(), "Expected bootstrap module app/main.py to exist"
    tree = ast.parse(_read_text(main_py), filename=str(main_py))
    found_registration = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "add_middleware":
                for arg in node.args:
                    if isinstance(arg, ast.Name) and "ResponseSchemaValidator" == arg.id:
                        found_registration = True
                    if isinstance(arg, ast.Attribute) and arg.attr == "ResponseSchemaValidator":
                        found_registration = True
    assert found_registration, "Expected app.add_middleware(ResponseSchemaValidator, ...) in app/main.py"

    # Verify Epic D routes declare response schemas (string refs in code)
    routes_by_path = _route_index_by_path()
    expected_map = {
        "/transforms/suggest": "SuggestResponse.json",
        "/transforms/preview": "TransformsPreviewResponse.json",
        "/transforms/catalog": "TransformsCatalogResponse.json",
        "/placeholders/bind": "BindResult.json",
        "/placeholders/unbind": "UnbindResponse.json",
        "/questions/{id}/placeholders": "ListPlaceholdersResponse.json",
        "/documents/{id}/bindings:purge": "PurgeResponse.json",
    }
    for route_path, schema_name in expected_map.items():
        defs = routes_by_path.get(route_path, [])
        assert defs, f"Expected route '{route_path}' to be registered"
        src = _read_text(defs[0].file)
        assert schema_name in src, f"{route_path} should reference schemas/{schema_name}"


# 7.1.19 — Deterministic transform engine exposed as a discrete service
def test_7_1_19_transform_engine_isolated_service() -> None:
    """Asserts a discrete transform engine service exists and is isolated from web layers."""
    # Verifies section 7.1.19
    # Service module presence (e.g., app/logic/transform_engine.py)
    engine_candidates = list((PROJECT_ROOT / "app" / "logic").glob("transform_*.py"))
    assert engine_candidates, (
        "Expected a standalone transform engine service module under app/logic (e.g., transform_engine.py)"
    )
    # Handlers import the service and service doesn't import web layers
    routes_by_path = _route_index_by_path()
    for route in ("/transforms/suggest", "/transforms/preview"):
        defs = routes_by_path.get(route, [])
        assert defs, f"Expected route '{route}' to be registered"
        src = _read_text(defs[0].file)
        assert re.search(r"from\s+app\.logic\.|import\s+app\.logic\.", src), (
            f"{route} handler should import the transform engine service from app.logic"
        )
    # Engine isolation: ensure no web transport imports
    for path in engine_candidates:
        imports = _list_top_level_imports(path)
        assert not any(re.search(r"fastapi|starlette", m) for m in imports), (
            f"Transform engine service must not import web layers: {path}"
        )


# 7.1.20 — Canonical value enforcement present in validation layer
def test_7_1_20_canonical_value_enforcement_present() -> None:
    """Asserts canonical value enforcement exists via schema or explicit validator usage."""
    # Verifies section 7.1.20
    # Accept either schema pattern on OptionSpec.value (already asserted in 7.1.9) or
    # presence of an explicit validator utility referenced by builders.
    optionspec = SCHEMAS_DIR / "OptionSpec.json"
    assert optionspec.exists(), "schemas/OptionSpec.json must exist."
    schema = _load_json(optionspec)
    value = _get_prop(schema, "value")
    pattern = value.get("pattern")
    has_pattern = isinstance(pattern, str) and pattern.strip() != ""
    if not has_pattern:
        # Fall back to explicit AST import and call of validator utility, scoped to suggest/preview
        routes_by_path = _route_index_by_path()
        validator_ok = True
        for route in ("/transforms/suggest", "/transforms/preview"):
            defs = routes_by_path.get(route, [])
            assert defs, f"Expected route '{route}' to be registered"
            mod_path = defs[0].file
            try:
                tree = ast.parse(_read_text(mod_path), filename=str(mod_path))
            except SyntaxError as exc:
                pytest.fail(f"Failed to parse {mod_path}: {exc}")
            # Collect imported validator symbols and module aliases
            imported_funcs: Set[str] = set()
            imported_modules: Set[str] = set()
            for node in tree.body:
                if isinstance(node, ast.ImportFrom) and node.module:
                    if re.search(r"validator|validate|canon|builder", node.module, re.IGNORECASE):
                        for a in node.names:
                            imported_funcs.add(a.asname or a.name)
                elif isinstance(node, ast.Import):
                    for a in node.names:
                        name = a.asname or a.name.split(".")[-1]
                        if re.search(r"validator|validate|canon|builder", a.name, re.IGNORECASE):
                            imported_modules.add(name)

            fdefs = _find_route_functions(mod_path, route)
            assert fdefs, f"Could not locate route function for '{route}'."
            fn = fdefs[0]
            found_call = False
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    # direct name call
                    if isinstance(node.func, ast.Name):
                        name = node.func.id
                        if (any(k in name.lower() for k in ("validate", "canonical", "canon")) and name in imported_funcs):
                            found_call = True
                            break
                    # module.attr call where module alias was imported
                    if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                        base = node.func.value.id
                        attr = node.func.attr
                        if base in imported_modules and any(k in attr.lower() for k in ("validate", "canonical", "canon")):
                            found_call = True
                            break
            if not found_call:
                validator_ok = False
                break
        assert validator_ok, (
            "Suggest/preview must import and invoke a specific validator/canonicalizer for option values"
        )


# 7.1.21 — Nested placeholder linkage represented by FK
def test_7_1_21_nested_placeholder_linkage_fk() -> None:
    """Asserts nested placeholder linkage is represented by a FK to Placeholder."""
    # Verifies section 7.1.21
    # Inspect ORM/model or DDL presence for placeholder option linkage
    model_candidates = list((PROJECT_ROOT / "app").rglob("*placeholder*.py"))
    assert model_candidates, (
        "Expected placeholder-related model/module to exist for FK inspection"
    )
    found_fk_reference = False
    for path in model_candidates:
        text = _read_text(path)
        if re.search(r"placeholder_id.*ForeignKey|ForeignKey\(.*placeholder", text):
            found_fk_reference = True
            break
    assert found_fk_reference, (
        "Parent option structure should include a nullable ForeignKey placeholder_id to Placeholder PK"
    )


# 7.1.22 — Placeholder persistence has FKs and cascade semantics
def test_7_1_22_placeholder_persistence_fks_and_cascade() -> None:
    """Asserts FKs exist for placeholder persistence with cascade semantics configured."""
    # Verifies section 7.1.22
    # Search migrations or models for question_id/document_id FKs and ON DELETE CASCADE
    ddl_hits = []
    for path in (PROJECT_ROOT / "migrations").rglob("*.sql"):
        text = _read_text(path)
        if "placeholder" in text.lower():
            ddl_hits.append((path, text))
    model_hits = []
    for path in (PROJECT_ROOT / "app").rglob("*.py"):
        text = _read_text(path)
        if re.search(r"question_id.*ForeignKey|document_id.*ForeignKey", text):
            model_hits.append((path, text))
    assert ddl_hits or model_hits, (
        "Expected DDL or ORM models declaring FKs for question_id and document_id with cascade semantics"
    )
    if ddl_hits:
        found_cascade = any("ON DELETE CASCADE" in t[1].upper() for t in ddl_hits)
        assert found_cascade, "document_id FK should be configured with ON DELETE CASCADE"
    else:
        # ORM-level cascade semantics detection
        orm_cascade = False
        for _, text in model_hits:
            if re.search(r"ondelete\s*=\s*['\"]CASCADE['\"]", text) or re.search(r"passive_deletes\s*=\s*True", text):
                orm_cascade = True
                break
        assert orm_cascade, "ORM models should express cascade semantics when no DDL is present"


# 7.1.23 — Catalog response schemas present and deterministic
def test_7_1_23_catalog_schemas_present_and_deterministic_ordering() -> None:
    """Asserts catalog response schemas exist and handler applies deterministic ordering."""
    # Verifies section 7.1.23
    resp = SCHEMAS_DIR / "TransformsCatalogResponse.json"
    item = SCHEMAS_DIR / "TransformsCatalogItem.json"
    assert resp.exists(), "schemas/TransformsCatalogResponse.json must exist."
    assert item.exists(), "schemas/TransformsCatalogItem.json must exist."
    # Handler references and ordering hint
    routes_by_path = _route_index_by_path()
    catalog_defs = routes_by_path.get("/transforms/catalog", [])
    assert catalog_defs, "Catalog handler not found; expected '/transforms/catalog'."
    catalog_path = catalog_defs[0].file
    src = _read_text(catalog_path)
    assert "TransformsCatalogResponse.json" in src, (
        "Catalog handler should reference TransformsCatalogResponse.json"
    )
    # Strengthen: ensure sort is applied within the decorated function
    fn_defs = _find_route_functions(catalog_path, "/transforms/catalog")
    assert fn_defs, "Could not locate catalog route function via decorator AST."
    has_sort = False
    for node in ast.walk(fn_defs[0]):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "sorted":
                has_sort = True
                break
            if isinstance(node.func, ast.Attribute) and node.func.attr == "sort":
                has_sort = True
                break
    assert has_sort, "Catalog route should sort items deterministically before responding"


# 7.1.24 — Timestamp format enforcement in schemas
def test_7_1_24_timestamp_format_enforced_in_schemas() -> None:
    """Asserts timestamp fields in schemas use RFC3339 date-time format."""
    # Verifies section 7.1.24
    ph = SCHEMAS_DIR / "Placeholder.json"
    assert ph.exists(), "schemas/Placeholder.json must exist."
    ph_schema = _load_json(ph)
    created_at = _get_prop(ph_schema, "created_at")
    assert created_at.get("format") == "date-time", "created_at must have format: date-time"
    # No alternative timestamp fields omit the format
    props = ph_schema.get("properties", {})
    for name, subschema in props.items():
        if "time" in name and isinstance(subschema, dict):
            if name != "created_at":
                assert subschema.get("format") == "date-time", (
                    f"Timestamp field '{name}' should have format: date-time"
                )


# 7.1.25 — Response projection for unbind is schema-validated
def test_7_1_25_unbind_response_projection_schema_validated() -> None:
    """Asserts unbind response projection is validated via schema reference."""
    # Verifies section 7.1.25
    path = SCHEMAS_DIR / "UnbindResponse.json"
    routes_by_path = _route_index_by_path()
    unbind_defs = routes_by_path.get("/placeholders/unbind", [])
    assert unbind_defs, "Unbind handler not found; expected '/placeholders/unbind'."
    src = _read_text(unbind_defs[0].file)
    if path.exists():
        assert "UnbindResponse.json" in src, (
            "Unbind handler should reference schemas/UnbindResponse.json"
        )
    else:
        # Otherwise enforce projection keys presence in code (static names)
        for key in ("ok", "question_id", "etag"):
            assert key in src, f"Unbind response projection should include key '{key}'"


# 7.1.26 — Probe immutability guard present on bind
def test_7_1_26_probe_immutability_guard_on_bind() -> None:
    """Asserts bind does not mutate probe and verifies probe via a guard function."""
    # Verifies section 7.1.26
    routes_by_path = _route_index_by_path()
    bind_defs = routes_by_path.get("/placeholders/bind", [])
    assert bind_defs, "Bind handler not found; expected '/placeholders/bind'."
    path = bind_defs[0].file
    src = _read_text(path)
    tree = ast.parse(src, filename=str(path))
    # Ensure no assignments to probe or its attributes/subscripts
    mutates_probe = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = []
            if isinstance(node, ast.Assign):
                targets = node.targets
            else:
                targets = [node.target]  # type: ignore[attr-defined]
            for t in targets:
                if isinstance(t, ast.Name) and t.id == "probe":
                    mutates_probe = True
                if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "probe":
                    mutates_probe = True
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) and t.value.id == "probe":
                    mutates_probe = True
    assert not mutates_probe, "Bind handler should not mutate probe fields; treat ProbeReceipt as immutable"
    # Must call a verification routine for the probe
    calls_verifier = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = None
            if isinstance(fn, ast.Name):
                name = fn.id
            elif isinstance(fn, ast.Attribute):
                name = fn.attr
            if name and any(p in name.lower() for p in ("verify", "validate", "check")):
                for arg in node.args:
                    if isinstance(arg, ast.Name) and arg.id == "probe":
                        calls_verifier = True
                        break
        if calls_verifier:
            break
    assert calls_verifier, "Bind handler should call a verification function for ProbeReceipt"


# 7.1.27 — Global schema validation enabled for all Epic D endpoints
def test_7_1_27_all_epic_d_routes_wire_response_schemas() -> None:
    """Asserts all Epic D routes wire response schemas for global validation."""
    # Verifies section 7.1.27
    routes_by_path = _route_index_by_path()
    expected_map = {
        "/transforms/suggest": "SuggestResponse.json",
        "/transforms/preview": "TransformsPreviewResponse.json",
        "/transforms/catalog": "TransformsCatalogResponse.json",
        "/placeholders/bind": "BindResult.json",
        "/placeholders/unbind": "UnbindResponse.json",
        "/questions/{id}/placeholders": "ListPlaceholdersResponse.json",
        "/documents/{id}/bindings:purge": "PurgeResponse.json",
    }
    for route_path, schema_name in expected_map.items():
        defs = routes_by_path.get(route_path, [])
        assert defs, f"Expected route '{route_path}' to be registered"
        src = _read_text(defs[0].file)
        assert schema_name in src, f"{route_path} should reference schemas/{schema_name}"
