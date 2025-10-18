"""Architectural tests for EPIC K — API Contract and Versioning.

These are static, file/AST-based checks designed to enforce contract-level
architecture before implementation exists. Each test maps 1:1 to a section
in 7.1 of the EPIC K spec and asserts only the requirements listed there.

Runner stability: these tests avoid executing application code and only read
files under the project root. Any parsing errors are caught and surfaced as
assertions rather than causing crashes.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple, Optional, Set

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = PROJECT_ROOT / "app"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"
DOCS_DIR = PROJECT_ROOT / "docs"


# --------------------
# Helper utilities
# --------------------


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

    Example: _get_prop(schema, "headers") returns the
    property-schema for `schema.properties.headers`.
    Fails with a clear assertion if any level is missing.
    """
    current = schema
    if not path:
        return current
    props = current.get("properties")
    if not isinstance(props, dict):
        pytest.fail("Schema has no top-level 'properties' object where expected.")
    key = path[0]
    if key not in props:
        pytest.fail(f"Missing property '{key}' in schema properties.")
    current = props[key]
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


def _iter_py_files(root: Path) -> Iterable[Path]:
    """Yield Python source files under a root directory."""
    if not root.exists():
        return []  # type: ignore[return-value]
    for path in root.rglob("*.py"):
        # Skip __pycache__ or virtualenv
        if any(part == "__pycache__" for part in path.parts):
            continue
        if ".venv" in path.parts:
            continue
        yield path


def _parse_ast(path: Path) -> ast.AST:
    try:
        src = path.read_text(encoding="utf-8")
    except Exception as exc:
        pytest.fail(f"Failed to read Python file for AST parse: {path} ({exc})")
    try:
        return ast.parse(src)
    except SyntaxError as exc:
        pytest.fail(f"Syntax error in {path}: {exc}")


def _function_defs(node: ast.AST) -> List[ast.FunctionDef]:
    return [n for n in ast.walk(node) if isinstance(n, ast.FunctionDef)]


def _contains_string_literal(node: ast.AST, text: str) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and text in n.value:
            return True
    return False


def _file_contains(path: Path, pattern: re.Pattern[str]) -> bool:
    try:
        return bool(pattern.search(path.read_text(encoding="utf-8")))
    except Exception:
        return False


def _scan_for_header_sets(py_file: Path) -> List[Tuple[int, str]]:
    """Return list of (lineno, header_name) for direct Response.headers[...] sets."""
    results: List[Tuple[int, str]] = []
    try:
        src = py_file.read_text(encoding="utf-8")
    except Exception:
        return results
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return results
    class _HeaderSubscripts(ast.NodeVisitor):
        def visit_Assign(self, node: ast.Assign) -> None:  # type: ignore[override]
            # Look for patterns: <name>.headers["Header-Name"] = ...
            target_nodes: list[ast.expr] = []
            # Support a, b = ... (multiple targets)
            for tgt in node.targets:
                target_nodes.append(tgt)
            for tgt in target_nodes:
                if isinstance(tgt, ast.Subscript):
                    # Python 3.8 vs 3.9 slice AST differs
                    key_node: Optional[ast.AST] = None
                    if hasattr(tgt, "slice"):
                        sl = getattr(tgt, "slice")
                        if isinstance(sl, ast.Index):  # py<3.9
                            key_node = sl.value
                        else:
                            key_node = sl
                    if (
                        isinstance(tgt.value, ast.Attribute)
                        and tgt.value.attr == "headers"
                        and isinstance(key_node, ast.Constant)
                        and isinstance(key_node.value, str)
                    ):
                        results.append((node.lineno, str(key_node.value)))
            self.generic_visit(node)

    _HeaderSubscripts().visit(tree)
    return results


def _walk_json(obj: Any) -> Iterable[Any]:
    stack = [obj]
    while stack:
        cur = stack.pop()
        yield cur
        if isinstance(cur, dict):
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)


# --------------------
# Tests — One per 7.1.x section
# --------------------


# 7.1.1 — Shared If-Match normaliser exists and is single-source
def test_7_1_1_shared_if_match_normaliser_single_source() -> None:
    """Verifies single shared If-Match normaliser and guard usage (7.1.1)."""
    # Verifies section 7.1.1
    assert APP_DIR.exists(), "app/ directory must exist."
    # Detect functions that perform If-Match/ETag normalisation using AST heuristics
    def _looks_like_normaliser(fn: ast.FunctionDef) -> bool:
        # Heuristics: uses string ops (strip/lower/startswith), references 'W/' or quotes,
        # and mentions If-Match/ETag in string constants or variable names
        ops = {"strip", "lower", "startswith", "replace", "split"}
        saw_op = False
        saw_marker = False
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                if n.func.attr in ops:
                    saw_op = True
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                v = n.value
                if ("If-Match" in v) or ("ETag" in v) or ("W/" in v) or ('"' in v):
                    saw_marker = True
            if isinstance(n, ast.Name) and re.search(r"if_?match|etag|token", n.id, re.IGNORECASE):
                saw_marker = True
        # Also require function name hints around normalize/normalise
        name_hint = re.search(r"normalis|normaliz|normalize|normalise", fn.name, re.IGNORECASE) is not None
        return name_hint and saw_op and saw_marker

    candidates: list[tuple[Path, str]] = []
    for py in _iter_py_files(APP_DIR):
        tree = _parse_ast(py)
        for fn in _function_defs(tree):
            if _looks_like_normaliser(fn):
                candidates.append((py, fn.name))

    # Expect exactly one normaliser implementation across app/
    assert len(candidates) == 1, (
        "Exactly one shared If-Match normaliser must exist across app/: "
        f"found {len(candidates)} -> {[str(p) + '::' + n for p, n in candidates]}"
    )

    # Assert precondition guard module imports/uses the shared normaliser
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "Guard module app/guards/precondition.py must exist."
    guard_src = guard_mod.read_text(encoding="utf-8")
    assert re.search(r"from\s+app\.logic\.etag\s+import\s+", guard_src), (
        "Precondition guard must import shared If-Match normaliser from app.logic.etag"
    )


# 7.1.2 — Precondition guard implemented as discrete middleware
def test_7_1_2_precondition_guard_is_middleware() -> None:
    """Asserts a discrete guard exists; handlers don't inline If-Match logic (7.1.2)."""
    # Verifies section 7.1.2
    assert APP_DIR.exists(), "app/ directory must exist."
    # Discrete guard symbol must be exported from a dedicated module
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "Guard module app/guards/precondition.py must exist."
    tree = _parse_ast(guard_mod)
    guard_defs = [fn for fn in _function_defs(tree) if fn.name == "precondition_guard"]
    assert guard_defs, "Guard module must define function 'precondition_guard'."

    # Route modules should import the guard symbol
    def _module_imports_guard(module_path: Path) -> bool:
        t = _parse_ast(module_path)
        for n in ast.walk(t):
            if isinstance(n, ast.ImportFrom):
                if n.module and n.module.startswith("app.guards"):
                    for alias in n.names:
                        if alias.name == "precondition_guard":
                            return True
        return False

    route_targets = [APP_DIR / "routes" / "answers.py", APP_DIR / "routes" / "documents.py"]
    for py in route_targets:
        assert py.exists(), f"Required route module missing: {py}"
        assert _module_imports_guard(py), f"{py.name} must import precondition_guard."

    # Mutation handlers must not inline If-Match parsing/comparison logic
    def _has_inline_if_match_logic(module_path: Path) -> list[str]:
        offenders: list[str] = []
        t = _parse_ast(module_path)
        for fn in _function_defs(t):
            # Consider only handlers with router method decorators
            has_route_decorator = any(
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr.lower() in {"post", "patch", "delete"}
                for dec in fn.decorator_list
            )
            if not has_route_decorator:
                continue

            saw_if_match_header = False
            saw_targeted_string_ops = False
            saw_compare_inline = False

            def _is_if_match_access(expr: ast.AST) -> bool:
                # Name 'if_match' or variants
                if isinstance(expr, ast.Name) and re.search(r"^(if_?match|etag|token)$", expr.id, re.IGNORECASE):
                    return True
                # headers['If-Match']
                if isinstance(expr, ast.Subscript):
                    base = expr.value
                    # Attribute like request.headers[...]
                    if isinstance(base, ast.Attribute) and base.attr == "headers":
                        key = getattr(expr, "slice", None)
                        if isinstance(key, ast.Index):  # py<3.9 compatibility
                            key = key.value
                        if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value == "If-Match":
                            return True
                return False

            for node in ast.walk(fn):
                # If-Match header usage via parameter name or headers access
                if isinstance(node, ast.Name) and re.search(r"^(if_?match|etag|token)$", node.id, re.IGNORECASE):
                    saw_if_match_header = True
                if isinstance(node, ast.Subscript):
                    if _is_if_match_access(node):
                        saw_if_match_header = True
                # Targeted string ops applied to If-Match token only
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in {"strip", "lower", "startswith", "replace", "split"}:
                        if _is_if_match_access(node.func.value):
                            saw_targeted_string_ops = True
                # Direct compare/normalizer usage
                if isinstance(node, ast.Name) and node.id in {"compare_etag", "_normalize_etag_token"}:
                    saw_compare_inline = True

            if saw_if_match_header and (saw_targeted_string_ops or saw_compare_inline):
                offenders.append(fn.name)
        return offenders

    for py in route_targets:
        offenders = _has_inline_if_match_logic(py)
        assert not offenders, (
            f"Mutation handlers must not inline If-Match logic; use guard. Offenders in {py.name}: "
            + ", ".join(offenders)
        )


# 7.1.3 — Guard mounted only on write routes (answers/documents)
def test_7_1_3_guard_mounted_on_write_routes() -> None:
    """Asserts guard is mounted only on write routes and before handlers (7.1.3)."""
    # Verifies section 7.1.3
    def _extract_route_info(module_path: Path) -> Tuple[Set[str], Set[str]]:
        """Return (write_with_guard, get_with_guard) function names for the module."""
        has_guard_on_write: set[str] = set()
        has_guard_on_get: set[str] = set()
        t = _parse_ast(module_path)
        for fn in _function_defs(t):
            # Determine HTTP method from decorators
            methods: set[str] = set()
            depends_found = False
            for dec in fn.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    methods.add(dec.func.attr.lower())
                    # dependencies=[Depends(precondition_guard)]
                    for kw in dec.keywords or []:
                        if kw.arg == "dependencies" and isinstance(kw.value, (ast.List, ast.Tuple)):
                            for elt in kw.value.elts:
                                if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name) and elt.func.id == "Depends":
                                    if elt.args and isinstance(elt.args[0], ast.Name) and elt.args[0].id == "precondition_guard":
                                        depends_found = True
                # Also check for parameter default Depends(precondition_guard)
            for arg in fn.args.args:
                if isinstance(arg.annotation, ast.AST):
                    pass  # not relevant
                if isinstance(arg, ast.arg) and hasattr(arg, "annotation"):
                    # default value lives elsewhere; we check separately
                    pass
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Depends":
                    if node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "precondition_guard":
                        depends_found = True
            if not methods:
                continue
            if any(m in {"post", "patch", "delete"} for m in methods):
                if depends_found:
                    has_guard_on_write.add(fn.name)
            if "get" in methods:
                if depends_found:
                    has_guard_on_get.add(fn.name)
        return has_guard_on_write, has_guard_on_get

    for py in [APP_DIR / "routes" / "answers.py", APP_DIR / "routes" / "documents.py"]:
        assert py.exists(), f"Required route module missing: {py}"
        write_guard, get_guard = _extract_route_info(py)
        assert write_guard, f"Guard must be mounted on write routes in {py.name}."
        assert not get_guard, f"Guard must not be mounted on GET routes in {py.name}."


# 7.1.4 — Guard not mounted on authoring routes (Phase‑0)
def test_7_1_4_guard_not_mounted_on_authoring_routes() -> None:
    """Ensures authoring APIs do not import or mount the guard (7.1.4)."""
    # Verifies section 7.1.4
    authoring = APP_DIR / "routes" / "authoring.py"
    assert authoring.exists(), "Authoring routes must be present to enforce 7.1.4."
    t = _parse_ast(authoring)
    # No import of precondition_guard
    for n in ast.walk(t):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("app.guards"):
            for alias in n.names:
                assert alias.name != "precondition_guard", (
                    "Authoring routes must not import precondition_guard in Phase-0."
                )
        # No decorator dependencies using precondition_guard
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "Depends":
            if n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == "precondition_guard":
                pytest.fail("Authoring routes must not depend on precondition_guard in Phase-0.")


# 7.1.5 — Central header‑emission utility is used
def test_7_1_5_central_header_emitter_is_used() -> None:
    """Asserts a single central header emitter is used; no direct sets (7.1.5)."""
    # Verifies section 7.1.5
    emitter_mod = APP_DIR / "logic" / "header_emitter.py"
    assert emitter_mod.exists(), "app/logic/header_emitter.py must exist."
    emitter_tree = _parse_ast(emitter_mod)
    emitter_funcs = [fn for fn in _function_defs(emitter_tree) if fn.name == "emit_etag_headers"]
    assert emitter_funcs, "header_emitter.emit_etag_headers function must be defined."

    required_headers = {"ETag", "Screen-ETag", "Question-ETag", "Questionnaire-ETag", "Document-ETag"}
    offenders: list[str] = []
    for py in (APP_DIR / "routes").glob("*.py"):
        if py.name in {"test_support.py"}:
            continue
        src = py.read_text(encoding="utf-8")
        # Only enforce emitter usage for modules that reference relevant headers
        participates = any(h in src for h in required_headers)
        if not participates:
            continue
        t = _parse_ast(py)
        imported_emit = False
        called_emit = False
        for n in ast.walk(t):
            if isinstance(n, ast.ImportFrom) and n.module == "app.logic.header_emitter":
                for alias in n.names:
                    if alias.name == "emit_etag_headers":
                        imported_emit = True
            if isinstance(n, ast.Call):
                if isinstance(n.func, ast.Name) and n.func.id == "emit_etag_headers":
                    called_emit = True
                if isinstance(n.func, ast.Attribute) and n.func.attr == "emit_etag_headers":
                    called_emit = True
        if not imported_emit or not called_emit:
            offenders.append(f"{py.name} missing import/use of emit_etag_headers")
        for (_lineno, hdr) in _scan_for_header_sets(py):
            if hdr in required_headers:
                offenders.append(f"direct header set {hdr} in {py.name}")
    assert not offenders, (
        "Endpoints must import and call central emitter and avoid direct header sets: "
        + ", ".join(offenders)
    )


# 7.1.6 — Scope→header mapping centralised
def test_7_1_6_scope_to_header_mapping_centralised() -> None:
    """Asserts a single scope→header mapping exists and is reused (7.1.6)."""
    # Verifies section 7.1.6
    # Find a single central mapping constant SCOPE_TO_HEADER in app/logic/*
    mapping_locs: list[Path] = []
    mapping_content: dict[str, str] | None = None
    for py in (APP_DIR / "logic").glob("*.py"):
        t = _parse_ast(py)
        for n in ast.walk(t):
            if isinstance(n, ast.Assign):
                # Only consider simple Name targets
                names = [t.id for t in n.targets if isinstance(t, ast.Name)]
                if "SCOPE_TO_HEADER" in names and isinstance(n.value, ast.Dict):
                    keys: list[str] = []
                    vals: list[str] = []
                    for k in n.value.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            keys.append(k.value)
                    for v in n.value.values:
                        if isinstance(v, ast.Constant) and isinstance(v.value, str):
                            vals.append(v.value)
                    if set(keys) == {"screen", "question", "questionnaire", "document"} and set(vals) >= {
                        "Screen-ETag", "Question-ETag", "Questionnaire-ETag", "Document-ETag"
                    }:
                        mapping_locs.append(py)
                        mapping_content = dict(zip(keys, vals))
    assert len(mapping_locs) == 1, "Exactly one SCOPE_TO_HEADER mapping must exist under app/logic/."

    emitter_mod = APP_DIR / "logic" / "header_emitter.py"
    assert emitter_mod.exists(), "header_emitter.py must use SCOPE_TO_HEADER mapping."
    emitter_src = emitter_mod.read_text(encoding="utf-8")
    assert "SCOPE_TO_HEADER" in emitter_src, "Emitter must reference SCOPE_TO_HEADER."

    # Assert callers do not hard-code domain header names directly
    hardcoded_offenders: list[str] = []
    domain_headers = ["Screen-ETag", "Question-ETag", "Questionnaire-ETag", "Document-ETag"]
    for py in (APP_DIR / "routes").glob("*.py"):
        if py == emitter_mod:
            continue
        t = _parse_ast(py)
        for n in ast.walk(t):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in domain_headers:
                hardcoded_offenders.append(f"{py.name} uses hard-coded '{n.value}'")
    assert not hardcoded_offenders, (
        "Domain header names must not be hard-coded in route modules: " + ", ".join(hardcoded_offenders)
    )


# 7.1.7 — CORS exposes required ETag headers
def test_7_1_7_cors_exposes_required_etag_headers() -> None:
    """Asserts CORS exposes Screen-/Question-/Questionnaire-/Document-ETag and ETag (7.1.7)."""
    # Verifies section 7.1.7
    main_py = APP_DIR / "main.py"
    assert main_py.exists(), "app/main.py must exist."
    t = _parse_ast(main_py)
    found = False
    required = ["Screen-ETag", "Question-ETag", "Questionnaire-ETag", "Document-ETag", "ETag"]
    for n in ast.walk(t):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            if n.func.attr == "add_middleware":
                # First arg should be CORSMiddleware (Name or Attribute)
                if n.args and (
                    (isinstance(n.args[0], ast.Name) and n.args[0].id == "CORSMiddleware")
                    or (isinstance(n.args[0], ast.Attribute) and n.args[0].attr == "CORSMiddleware")
                ):
                    for kw in n.keywords or []:
                        if kw.arg == "expose_headers" and isinstance(kw.value, (ast.List, ast.Tuple)):
                            headers: list[str] = []
                            for elt in kw.value.elts:
                                if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                    headers.append(elt.value)
                            # Must include all required and contain no duplicates
                            if set(required).issubset(set(headers)) and len(headers) == len(set(headers)):
                                found = True
    assert found, (
        "CORSMiddleware expose_headers must include Screen-/Question-/Questionnaire-/Document-ETag and ETag,"
        " with no duplicates."
    )


# 7.1.8 — Outputs schema declares canonical keys
def test_7_1_8_outputs_schema_declares_canonical_keys() -> None:
    """Asserts Outputs.schema.json declares top-level headers and body only (7.1.8)."""
    # Verifies section 7.1.8
    path = SCHEMAS_DIR / "Outputs.schema.json"
    assert path.exists(), "schemas/Outputs.schema.json must exist."
    schema = _load_json(path)

    # Must define properties.headers and properties.body
    _ = _get_prop(schema, "headers")
    _ = _get_prop(schema, "body")

    # No unexpected top-level required keys beyond headers and body
    required = schema.get("required")
    if required is not None:
        assert set(required) <= {"headers", "body"}, (
            "Top-level required keys must be only ['headers', 'body']"
        )


# 7.1.9 — Outputs schema includes domain header fields
def test_7_1_9_outputs_schema_includes_domain_header_fields() -> None:
    """Asserts outputs.headers includes Screen-/Question-/Questionnaire-/Document-ETag and ETag (7.1.9)."""
    # Verifies section 7.1.9
    path = SCHEMAS_DIR / "Outputs.schema.json"
    assert path.exists(), "schemas/Outputs.schema.json must exist."
    schema = _load_json(path)

    headers = _get_prop(schema, "headers")
    props = headers.get("properties")
    assert isinstance(props, dict), "headers.properties must be an object."
    for key in ["Screen-ETag", "Question-ETag", "Questionnaire-ETag", "Document-ETag", "ETag"]:
        assert key in props, f"headers must declare property '{key}'."
        # Enforce $ref to token schema; plain string types are not acceptable
        prop = props[key]
        assert isinstance(prop, dict), f"headers.{key} must be a schema object."
        assert "$ref" in prop, f"headers.{key} must use a $ref to the token schema."
        ref = str(prop["$ref"])  # e.g., ./ETag.schema.json or ./EtagToken.schema.json
        assert re.search(r"ETag\.schema\.json|EtagToken\.schema\.json", ref), (
            f"headers.{key} should $ref ETag/EtagToken schema, got: {ref}"
        )

    # Assert that headers.required is absent or empty (not globally required)
    headers_required = headers.get("required")
    assert headers_required in (None, [], ()), (
        "headers.required must be absent or empty; do not require domain headers globally."
    )


# 7.1.10 — No new body mirrors introduced
def test_7_1_10_no_new_body_mirrors_introduced() -> None:
    """Asserts no outputs.etags and no new body mirrors beyond documented ones (7.1.10)."""
    # Verifies section 7.1.10
    outputs_path = SCHEMAS_DIR / "Outputs.schema.json"
    assert outputs_path.exists(), "schemas/Outputs.schema.json must exist."
    outputs_schema = _load_json(outputs_path)
    # Must not define 'etags' under top-level outputs
    top_props = outputs_schema.get("properties") or {}
    assert "etags" not in top_props, "Outputs.schema.json must not declare top-level 'etags'."

    # Disallow unexpected body mirrors named 'etag' outside body.screen_view.etag
    def _collect_etag_paths(schema: dict[str, Any], base: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
        paths: list[tuple[str, ...]] = []
        if not isinstance(schema, dict):
            return paths
        props = schema.get("properties")
        if isinstance(props, dict):
            for k, v in props.items():
                if k == "etag":
                    paths.append(base + (k,))
                elif isinstance(v, dict):
                    paths.extend(_collect_etag_paths(v, base + (k,)))
        return paths

    etag_paths = _collect_etag_paths(_get_prop(outputs_schema, "body"), ("body",))
    allowed = {("body", "screen_view", "etag")}
    unexpected = [".".join(p) for p in etag_paths if tuple(p) not in allowed]
    assert not unexpected, (
        "Unexpected body etag mirrors declared: " + ", ".join(unexpected)
    )


# 7.1.11 — Screen body mirror retained
def test_7_1_11_screen_body_mirror_retained() -> None:
    """Asserts schema and builder include body.screen_view.etag (7.1.11)."""
    # Verifies section 7.1.11
    path = SCHEMAS_DIR / "Outputs.schema.json"
    assert path.exists(), "schemas/Outputs.schema.json must exist."
    schema = _load_json(path)
    # Schema must include body.screen_view.etag
    body = _get_prop(schema, "body")
    # Traverse nested: body.screen_view.etag
    try:
        _ = _get_prop(schema, "body", "screen_view")
        etag_prop = _get_prop(schema, "body", "screen_view", "etag")
        assert isinstance(etag_prop, dict)
    except AssertionError as exc:
        pytest.fail(f"Outputs.schema.json must declare body.screen_view.etag: {exc}")

    # Response builder should assemble body['screen_view']['etag'] via AST
    assembly = APP_DIR / "logic" / "screen_builder.py"
    assert assembly.exists(), "app/logic/screen_builder.py must exist for screen assembly."
    t = _parse_ast(assembly)
    found_nested = False
    for n in ast.walk(t):
        # Detect dict literal with nested keys
        if isinstance(n, ast.Dict):
            keys = [k.value for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if "screen_view" in keys:
                # value at index of 'screen_view'
                idxs = [i for i, k in enumerate(n.keys) if isinstance(k, ast.Constant) and k.value == "screen_view"]
                for idx in idxs:
                    val = n.values[idx]
                    if isinstance(val, ast.Dict):
                        subkeys = [
                            k.value for k in val.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)
                        ]
                        if "etag" in subkeys:
                            found_nested = True
        # Detect assignment: body['screen_view']['etag'] = ...
        if isinstance(n, ast.Assign):
            for tgt in n.targets:
                if isinstance(tgt, ast.Subscript):
                    # pattern: X['screen_view']['etag']
                    inner = tgt
                    # First slice 'etag'
                    sl1 = getattr(inner, "slice", None)
                    if isinstance(sl1, ast.Index):
                        sl1 = sl1.value
                    if isinstance(sl1, ast.Constant) and sl1.value == "etag":
                        if isinstance(inner.value, ast.Subscript):
                            sl0 = getattr(inner.value, "slice", None)
                            if isinstance(sl0, ast.Index):
                                sl0 = sl0.value
                            if isinstance(sl0, ast.Constant) and sl0.value == "screen_view":
                                found_nested = True
    assert found_nested, "screen_builder must set or include body['screen_view']['etag'] in responses."


# 7.1.12 — Diagnostic headers preserved for reorder
def test_7_1_12_diagnostic_headers_preserved_for_reorder() -> None:
    """Asserts reorder handler delegates to emitter and emitter references diagnostics (7.1.12)."""
    # Verifies section 7.1.12 (aligned with 7.1.23 central emitter requirement)
    docs_routes = APP_DIR / "routes" / "documents.py"
    assert docs_routes.exists(), "app/routes/documents.py must exist."

    # (1) Reorder handler must import and call the central emitter
    t = _parse_ast(docs_routes)

    def _is_reorder_handler(fn: ast.FunctionDef) -> bool:
        for dec in fn.decorator_list:
            if isinstance(dec, ast.Call):
                for arg in dec.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "reorder" in arg.value:
                        return True
        return "reorder" in fn.name.lower()

    reorder_fns = [fn for fn in _function_defs(t) if _is_reorder_handler(fn)]
    assert reorder_fns, "documents.py must define a reorder handler."

    imported_emit = False
    for n in ast.walk(t):
        if isinstance(n, ast.ImportFrom) and n.module == "app.logic.header_emitter":
            for alias in n.names:
                if alias.name == "emit_etag_headers":
                    imported_emit = True
    assert imported_emit, "documents.py must import emit_etag_headers for reorder path."

    called_in_reorder = False
    for fn in reorder_fns:
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id == "emit_etag_headers":
                    called_in_reorder = True
                if isinstance(node.func, ast.Attribute) and node.func.attr == "emit_etag_headers":
                    called_in_reorder = True
    assert called_in_reorder, "Reorder handler must call emit_etag_headers."

    # (2) Central emitter must reference diagnostic header names
    emitter_mod = APP_DIR / "logic" / "header_emitter.py"
    assert emitter_mod.exists(), "app/logic/header_emitter.py must exist."
    emitter_src = emitter_mod.read_text(encoding="utf-8")
    for required in ("X-List-ETag", "X-If-Match-Normalized"):
        assert required in emitter_src, f"header_emitter must reference diagnostic header '{required}'."


# 7.1.13 — Token computation isolated and unchanged entry points
def test_7_1_13_token_computation_isolated_entrypoints_unchanged() -> None:
    """Asserts token compute isolated; public API unchanged; no private imports (7.1.13)."""
    # Verifies section 7.1.13
    etag_mod = APP_DIR / "logic" / "etag.py"
    assert etag_mod.exists(), "app/logic/etag.py must exist."
    etag_tree = _parse_ast(etag_mod)

    # etag.py must not import guard (avoid import cycle)
    for n in ast.walk(etag_tree):
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("app.guards"):
            pytest.fail("app/logic/etag.py must not import from app.guards (isolation).")

    # No private imports from app.logic.etag allowed in other modules
    private_imports: list[str] = []
    for py in _iter_py_files(APP_DIR):
        if py == etag_mod:
            continue
        try:
            t = _parse_ast(py)
        except Exception:
            continue
        for n in ast.walk(t):
            if isinstance(n, ast.ImportFrom) and n.module == "app.logic.etag":
                for alias in n.names:
                    if alias.name.startswith("_"):
                        private_imports.append(str(py))
    assert not private_imports, (
        "No module may import private names from app.logic.etag: " + ", ".join(private_imports)
    )

    # Public API surface of app/logic/etag.py must remain unchanged.
    # Collect exported callable names:
    # - If __all__ is defined, use it (string constants only)
    # - Else, use top-level non-private function definitions
    exported: set[str] = set()
    __all__vals: list[str] = []
    for n in etag_tree.body if isinstance(etag_tree, ast.Module) else []:  # type: ignore[attr-defined]
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == "__all__":
                    # Only accept a simple list of string constants
                    if isinstance(n.value, (ast.List, ast.Tuple)):
                        for elt in n.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                __all__vals.append(elt.value)
    if __all__vals:
        exported = set(__all__vals)
    else:
        for n in etag_tree.body if isinstance(etag_tree, ast.Module) else []:  # type: ignore[attr-defined]
            if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"):
                exported.add(n.name)

    # Baseline public API (fixed, contractually stable entry points).
    # This list encodes the expected callable surface from Phase‑0.
    baseline = {
        # Runtime/answers/screens
        "compute_screen_etag",
        # Authoring helpers
        "compute_authoring_screen_etag",
        "compute_authoring_screen_etag_from_order",
        "compute_authoring_question_etag",
        "compute_questionnaire_etag_for_authoring",
        # Documents/list
        "doc_etag",
        "compute_document_list_etag",
        # Normalised compare entry point (stable external API)
        "compare_etag",
    }

    # Assert exactly the same exported callables as baseline
    # to enforce "unchanged entry points".
    assert exported == baseline, (
        "app/logic/etag.py public API must remain unchanged.\n"
        f"Expected: {sorted(baseline)}\nFound:    {sorted(exported)}"
    )


# 7.1.14 — OpenAPI responses declare domain headers
def test_7_1_14_openapi_responses_declare_domain_headers() -> None:
    """Asserts OpenAPI specs declare headers per endpoint type (7.1.14)."""
    # Verifies section 7.1.14
    # Search for OpenAPI JSON or YAML in repo
    json_specs: list[Path] = list(DOCS_DIR.glob("**/*.json"))
    yaml_specs: list[Path] = list(DOCS_DIR.glob("**/*.yml")) + list(DOCS_DIR.glob("**/*.yaml"))
    openapi_dir = PROJECT_ROOT / "openapi"
    if openapi_dir.exists():
        json_specs += list(openapi_dir.glob("**/*.json"))
        yaml_specs += list(openapi_dir.glob("**/*.yml")) + list(openapi_dir.glob("**/*.yaml"))
    assert json_specs or yaml_specs, "OpenAPI spec files must be present in docs/ or openapi/."

    # Load all specs we can parse
    loaded_specs: list[dict] = []
    for p in json_specs:
        try:
            loaded_specs.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    if yaml_specs:
        try:
            import yaml  # type: ignore
        except Exception:
            yaml = None  # type: ignore
        if yaml is not None:  # type: ignore
            for p in yaml_specs:
                try:
                    loaded_specs.append(yaml.safe_load(p.read_text(encoding="utf-8")))  # type: ignore
                except Exception:
                    continue
    assert loaded_specs, "At least one OpenAPI spec (JSON or YAML) must be parseable."

    # Structured validation: paths -> methods -> responses -> headers
    saw_runtime = saw_authoring = saw_csv = False
    for spec in loaded_specs:
        paths = spec.get("paths", {})
        if not isinstance(paths, dict):
            continue
        paths = spec.get("paths", {})
        if not isinstance(paths, dict):
            continue
        for route, methods in paths.items():
            if not isinstance(methods, dict):
                continue
            for method, meta in methods.items():
                if not isinstance(meta, dict):
                    continue
                responses = meta.get("responses", {})
                if not isinstance(responses, dict):
                    continue
                for _code, resp in responses.items():
                    if not isinstance(resp, dict):
                        continue
                    headers = resp.get("headers", {})
                    if not isinstance(headers, dict):
                        continue
                    header_names = set(headers.keys())
                    # Heuristics for endpoint type
                    if "/response-sets/" in route and method.lower() == "get":
                        # runtime JSON GETs: domain + ETag must be present
                        has_domain = any(h in header_names for h in {"Screen-ETag", "Question-ETag", "Document-ETag"})
                        if has_domain and "ETag" in header_names:
                            saw_runtime = True
                    if "/authoring/" in route and method.lower() == "get":
                        # authoring JSON GETs: domain only (ETag must be absent)
                        has_domain = any(h in header_names for h in {"Screen-ETag", "Question-ETag", "Questionnaire-ETag", "Document-ETag"})
                        if has_domain:
                            assert "ETag" not in header_names, (
                                f"Authoring GET must not declare generic ETag in OpenAPI for {route}"
                            )
                            saw_authoring = True
                    if "/questionnaires/" in route and "export" in route and method.lower() == "get":
                        # CSV export: Questionnaire-ETag required; ETag may be present
                        if "Questionnaire-ETag" in header_names:
                            saw_csv = True
    assert saw_runtime and saw_authoring and saw_csv, (
        "OpenAPI must declare headers for runtime (domain+ETag), authoring (domain only), and CSV (Questionnaire-ETag)."
    )


# 7.1.15 — CSV/non‑JSON uses the central header emitter
def test_7_1_15_csv_export_uses_central_emitter() -> None:
    """Asserts CSV export uses central header emitter; no direct sets (7.1.15)."""
    # Verifies section 7.1.15
    csv_route = APP_DIR / "routes" / "questionnaires.py"
    assert csv_route.exists(), "app/routes/questionnaires.py must exist."
    t = _parse_ast(csv_route)
    imported_emit = False
    called_emit = False
    for n in ast.walk(t):
        if isinstance(n, ast.ImportFrom) and n.module == "app.logic.header_emitter":
            for alias in n.names:
                if alias.name == "emit_etag_headers":
                    imported_emit = True
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name) and n.func.id == "emit_etag_headers":
                called_emit = True
            if isinstance(n.func, ast.Attribute) and n.func.attr == "emit_etag_headers":
                called_emit = True
    assert imported_emit and called_emit, (
        "CSV export route must import and call the shared header emitter."
    )

    # Must not directly set ETag/Questionnaire-ETag
    for (_lineno, hdr) in _scan_for_header_sets(csv_route):
        assert hdr not in {"ETag", "Questionnaire-ETag"}, (
            "CSV export must not set ETag/Questionnaire-ETag directly; use emitter."
        )


# 7.1.16 — Logging interface defines etag event types and is used
def test_7_1_16_logging_defines_and_uses_etag_events() -> None:
    """Asserts logging declares etag events and guard/emitter log them with context (7.1.16)."""
    # Verifies section 7.1.16
    events_py = APP_DIR / "logic" / "events.py"
    assert events_py.exists(), "app/logic/events.py must exist."
    events_src = events_py.read_text(encoding="utf-8")
    # 1) Logger interface defines both event types (as string constants or values)
    assert "etag.enforce" in events_src and "etag.emit" in events_src, (
        "Logging interface must declare event types 'etag.enforce' and 'etag.emit'."
    )

    # Helper to scan a module for logger calls with a target event name and required context keys
    def _module_logs_event_with_keys(module_path: Path, event_name: str, required_keys: set[str]) -> bool:
        t = _parse_ast(module_path)
        for n in ast.walk(t):
            if isinstance(n, ast.Call):
                # Match logger.<level>(...)
                if isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) and n.func.value.id == "logger":
                    # Check positional args for the event token
                    has_event = False
                    for arg in n.args:
                        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and event_name in arg.value:
                            has_event = True
                    # Also inspect keywords for structured 'event' fields
                    for kw in n.keywords or []:
                        if isinstance(kw, ast.keyword) and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                            if event_name in kw.value.value:
                                has_event = True
                    if not has_event:
                        continue
                    # Verify required context keys mentioned as keyword names
                    keys_present = set(kw.arg for kw in (n.keywords or []) if isinstance(kw, ast.keyword) and isinstance(kw.arg, str))
                    if required_keys <= keys_present:
                        return True
        return False

    guard_py = APP_DIR / "guards" / "precondition.py"
    emitter_py = APP_DIR / "logic" / "header_emitter.py"
    assert guard_py.exists(), "app/guards/precondition.py must exist."
    assert emitter_py.exists(), "app/logic/header_emitter.py must exist."

    # 2) Guard logs etag.enforce with a boolean matched indicator
    assert _module_logs_event_with_keys(guard_py, "etag.enforce", {"matched"}), (
        "Precondition guard must log 'etag.enforce' with a 'matched' context field."
    )

    # 3) Emitter logs etag.emit with route/scope context (accept either key name)
    emitter_ok = (
        _module_logs_event_with_keys(emitter_py, "etag.emit", {"route"})
        or _module_logs_event_with_keys(emitter_py, "etag.emit", {"scope"})
    )
    assert emitter_ok, (
        "Header emitter must log 'etag.emit' with 'route' or 'scope' context."
    )


# 7.1.27 — Guard file has no module-scope DB driver imports (static AST check)
def test_7_1_27_guard_no_db_driver_imports() -> None:
    """Asserts guard avoids module-scope psycopg2 imports; flags dynamic __import__ (7.1.27)."""
    # Verifies section 7.1.27
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "Guard module app/guards/precondition.py must exist."

    # Parse AST and inspect only top-level (module-scope) statements for imports
    try:
        src = guard_mod.read_text(encoding="utf-8")
    except Exception as exc:  # Runner stability: surface as assertion
        pytest.fail(f"Failed to read guard module for 7.1.27: {exc}")
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        pytest.fail(f"Syntax error while parsing guard module for 7.1.27: {exc}")

    offenders: list[tuple[int, str]] = []

    def _is_psycopg2_name(name: str) -> bool:
        return name == "psycopg2" or name.startswith("psycopg2.")

    for node in getattr(tree, "body", []):
        # Assert: (1) No module-scope Import/ImportFrom references psycopg2 or submodules
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_psycopg2_name(alias.name):
                    offenders.append((getattr(node, "lineno", -1), f"import {alias.name}"))
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if _is_psycopg2_name(mod):
                offenders.append((getattr(node, "lineno", -1), f"from {mod} import ..."))

        # Assert: (3) No dynamic import disguises at module scope (e.g., __import__("psycopg2"))
        # Check any Call nodes nested directly under this top-level statement
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "__import__":
                if sub.args and isinstance(sub.args[0], ast.Constant) and isinstance(sub.args[0].value, str):
                    target = sub.args[0].value
                    if _is_psycopg2_name(target):
                        offenders.append((getattr(sub, "lineno", -1), f"__import__(\"{target}\")"))

    # Assert: (2) If any such import exists, the test fails and reports offending line numbers
    assert not offenders, (
        "app/guards/precondition.py must not import psycopg2 at module scope; "
        "offenders: " + ", ".join([f"line {ln}: {desc}" for ln, desc in offenders])
    )


# 7.1.28 — Guard file has no module-scope repository imports (static AST check)
def test_7_1_28_guard_no_module_scope_repository_imports() -> None:
    """Ensures guard avoids importing app.logic.repository_* at module scope (7.1.28)."""
    # Verifies section 7.1.28
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "Guard module app/guards/precondition.py must exist."

    try:
        src = guard_mod.read_text(encoding="utf-8")
    except Exception as exc:
        pytest.fail(f"Failed to read guard module for 7.1.28: {exc}")
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        pytest.fail(f"Syntax error while parsing guard module for 7.1.28: {exc}")

    offenders: list[tuple[int, str]] = []

    def _is_repo_module(mod: str) -> bool:
        return mod.startswith("app.logic.repository_")

    for node in getattr(tree, "body", []):
        # Assert: (1) No module-scope Import/ImportFrom targets any app.logic.repository_*
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _is_repo_module(alias.name):
                    offenders.append((getattr(node, "lineno", -1), f"import {alias.name}"))
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            # Direct "from app.logic.repository_x import ..."
            if _is_repo_module(mod):
                offenders.append((getattr(node, "lineno", -1), f"from {mod} import ..."))
            # Indirect via "from app.logic import repository_x as repo"
            if mod == "app.logic":
                for alias in node.names:
                    # Assert: (3) No indirect imports via wildcard or alias
                    if alias.name == "*" or alias.name.startswith("repository_"):
                        offenders.append((getattr(node, "lineno", -1), f"from app.logic import {alias.name}"))

    # Assert: (2) If any such import exists, test fails and reports offending line numbers
    assert not offenders, (
        "app/guards/precondition.py must not import repository modules at module scope; "
        "offenders: " + ", ".join([f"line {ln}: {desc}" for ln, desc in offenders])
    )


# 7.1.17 — Guard not mounted on any GET/read endpoints
def test_7_1_17_guard_not_mounted_on_any_get_endpoints() -> None:
    """Verifies 7.1.17 — GET routes must not reference `precondition_guard`."""
    routes_dir = APP_DIR / "routes"
    assert routes_dir.exists(), "app/routes/ directory must exist."

    def _fn_is_get_with_guard(fn: ast.FunctionDef) -> bool:
        is_get = False
        uses_guard = False
        # Decorators: detect @router.get(...)
        for dec in fn.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr.lower() == "get":
                is_get = True
                # dependencies=[Depends(precondition_guard)]
                for kw in dec.keywords or []:
                    if kw.arg == "dependencies" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        for elt in kw.value.elts:
                            if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name) and elt.func.id == "Depends":
                                if elt.args and isinstance(elt.args[0], ast.Name) and elt.args[0].id == "precondition_guard":
                                    uses_guard = True
        # Parameter defaults: def f(dep=Depends(precondition_guard))
        for default in list(fn.args.defaults or []) + list(fn.args.kw_defaults or []):  # type: ignore[attr-defined]
            if isinstance(default, ast.Call) and isinstance(default.func, ast.Name) and default.func.id == "Depends":
                if default.args and isinstance(default.args[0], ast.Name) and default.args[0].id == "precondition_guard":
                    uses_guard = True
        # Any inner Depends(precondition_guard) usage counts as violation for GET
        for node in ast.walk(fn):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Depends":
                if node.args and isinstance(node.args[0], ast.Name) and node.args[0].id == "precondition_guard":
                    uses_guard = True
        return is_get and uses_guard

    offenders: list[str] = []
    for py in _iter_py_files(routes_dir):
        t = _parse_ast(py)
        for fn in _function_defs(t):
            if _fn_is_get_with_guard(fn):
                offenders.append(f"{py.name}::{fn.name}")
    assert not offenders, (
        "GET/read routes must not reference precondition_guard: " + ", ".join(offenders)
    )


# 7.1.18 — Guard is DB-free and import-safe
def test_7_1_18_guard_is_db_free_and_import_safe() -> None:
    """Verifies 7.1.18 — Lazy import of ETag helpers and no DB/repo imports at module scope."""
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "Guard module app/guards/precondition.py must exist."
    t = _parse_ast(guard_mod)

    # Assert: no module-scope Import/ImportFrom of app.logic.etag
    for node in getattr(t, "body", []):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.logic.etag"):
            pytest.fail("Guard must not import app.logic.etag at module scope (lazy import required).")
        if isinstance(node, ast.Import) and any(alias.name.startswith("app.logic.etag") for alias in node.names):
            pytest.fail("Guard must not import app.logic.etag at module scope (lazy import required).")

    # Assert: at least one function body contains ImportFrom app.logic.etag
    found_lazy_etag_import = False
    for fn in _function_defs(t):
        for node in fn.body:
            for sub in ast.walk(node):
                if isinstance(sub, ast.ImportFrom) and (sub.module or "").startswith("app.logic.etag"):
                    found_lazy_etag_import = True
    assert found_lazy_etag_import, (
        "Guard must locally import app.logic.etag inside function scope(s) to enforce DB-free isolation."
    )

    # Assert: no module-scope imports of DB drivers or repositories
    denied_modules = {"psycopg2"}
    for node in getattr(t, "body", []):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in denied_modules or alias.name.startswith("psycopg2"):
                    pytest.fail("Guard must be DB-free at module scope (no psycopg2 imports).")
                if alias.name.startswith("app.logic.repository_"):
                    pytest.fail("Guard must not import repositories at module scope.")
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in denied_modules or mod.startswith("psycopg2"):
                pytest.fail("Guard must be DB-free at module scope (no psycopg2 imports).")
            if mod.startswith("app.logic.repository_"):
                pytest.fail("Guard must not import repositories at module scope.")


# 7.1.19 — Handlers contain no inline precondition logic
def test_7_1_19_handlers_contain_no_inline_precondition_logic() -> None:
    """Verifies 7.1.19 — Mutation handlers must not parse/compare If-Match inline anywhere in app/routes/."""
    routes_dir = APP_DIR / "routes"
    assert routes_dir.exists(), "app/routes/ directory must exist."

    def _mutation_handler(fn: ast.FunctionDef) -> bool:
        for dec in fn.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if dec.func.attr.lower() in {"post", "patch", "delete"}:
                    return True
        return False

    def _has_inline_precondition_logic(fn: ast.FunctionDef) -> bool:
        # Only flag when the handler both (a) explicitly reads If-Match and
        # (b) performs string ops or compares that token inline.
        def _is_if_match_access(expr: ast.AST) -> bool:
            if isinstance(expr, ast.Name) and re.search(r"^(if_?match|etag|token)$", expr.id, re.IGNORECASE):
                return True
            if isinstance(expr, ast.Subscript):
                base = expr.value
                if isinstance(base, ast.Attribute) and base.attr == "headers":
                    key = getattr(expr, "slice", None)
                    if isinstance(key, ast.Index):
                        key = key.value
                    if isinstance(key, ast.Constant) and isinstance(key.value, str) and key.value == "If-Match":
                        return True
            return False

        saw_if_match = False
        saw_targeted_string_ops = False
        saw_compare = False

        for node in ast.walk(fn):
            # Explicit If-Match usage via parameter or headers access
            if isinstance(node, ast.Name) and re.search(r"^(if_?match|etag|token)$", node.id, re.IGNORECASE):
                saw_if_match = True
            if isinstance(node, ast.Subscript) and _is_if_match_access(node):
                saw_if_match = True
            # Targeted string ops only when applied to If-Match access
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in {"strip", "lower", "startswith", "replace", "split"}:
                    if _is_if_match_access(node.func.value):
                        saw_targeted_string_ops = True
            # Direct compare or normalizer references remain forbidden
            if isinstance(node, ast.Name) and node.id in {"compare_etag", "_normalize_etag_token"}:
                saw_compare = True

        return saw_if_match and (saw_targeted_string_ops or saw_compare)

    offenders: list[str] = []
    for py in _iter_py_files(routes_dir):
        t = _parse_ast(py)
        for fn in _function_defs(t):
            if _mutation_handler(fn) and _has_inline_precondition_logic(fn):
                offenders.append(f"{py.name}::{fn.name}")
    assert not offenders, (
        "Mutation handlers must not inline If-Match parsing/compare logic; use the precondition guard: "
        + ", ".join(offenders)
    )


# 7.1.20 — Stable problem+json mapping for preconditions
def test_7_1_20_stable_problem_json_mapping_for_preconditions() -> None:
    """Verifies 7.1.20 — Guard maps missing→428 PRE_IF_MATCH_MISSING and mismatch→409/412 PRE_IF_MATCH_ETAG_MISMATCH."""
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "Guard module app/guards/precondition.py must exist."
    src = guard_mod.read_text(encoding="utf-8")
    tree = _parse_ast(guard_mod)

    # Assert presence of invariant error codes
    assert "PRE_IF_MATCH_MISSING" in src, "Guard must define code PRE_IF_MATCH_MISSING."
    assert "PRE_IF_MATCH_ETAG_MISMATCH" in src, "Guard must define code PRE_IF_MATCH_ETAG_MISMATCH."

    # Assert presence of 428 and both mismatch status codes (409 and 412) in module
    numeric_constants: set[int] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and isinstance(n.value, int):
            numeric_constants.add(int(n.value))
    assert 428 in numeric_constants, "Guard must construct 428 Precondition Required for missing If-Match."
    missing_codes = {409, 412} - numeric_constants
    assert not missing_codes, (
        "Guard must construct both mismatch statuses: 409 (answers) and 412 (documents). Missing: "
        + ", ".join(str(c) for c in sorted(missing_codes))
    )

    # Assert problem body includes a 'code' key in at least one construction site
    has_code_key = False
    for n in ast.walk(tree):
        if isinstance(n, ast.Dict):
            for k in n.keys:
                if isinstance(k, ast.Constant) and k.value == "code":
                    has_code_key = True
    assert has_code_key, "Problem+json bodies constructed by guard must include a 'code' field."


# 7.1.21 — OpenAPI declares If-Match as required on write routes
def test_7_1_21_openapi_declares_if_match_required_on_write_routes() -> None:
    """Verifies 7.1.21 — OpenAPI declares required If-Match and route-specific mismatch codes (answers→409, documents→412)."""
    # Discover OpenAPI specs
    json_specs: list[Path] = list(DOCS_DIR.glob("**/*.json"))
    yaml_specs: list[Path] = list(DOCS_DIR.glob("**/*.yaml")) + list(DOCS_DIR.glob("**/*.yml"))
    openapi_dir = PROJECT_ROOT / "openapi"
    if openapi_dir.exists():
        json_specs += list(openapi_dir.glob("**/*.json"))
        yaml_specs += list(openapi_dir.glob("**/*.yaml")) + list(openapi_dir.glob("**/*.yml"))
    assert json_specs or yaml_specs, "OpenAPI spec files must exist under docs/ or openapi/."

    loaded: list[dict] = []
    for p in json_specs:
        try:
            loaded.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            # Ignore unreadable JSON spec files
            continue
    try:
        import yaml  # type: ignore
    except Exception:
        yaml = None  # type: ignore
    for p in yaml_specs:
        if yaml is None:
            continue
        try:
            loaded.append(yaml.safe_load(p.read_text(encoding="utf-8")))  # type: ignore[attr-defined]
        except Exception:
            continue
    assert loaded, "At least one OpenAPI document must parse successfully."

    def _iter_operations(spec: dict) -> Iterable[tuple[str, str, dict]]:
        """Yield only Phase-0 in-scope operations for If-Match requirements.

        Scope:
        - PATCH paths containing '/response-sets/' and '/answers/' (per-answer autosave)
        - PUT paths '/documents/order' and, if present, PUT '/documents/{id}/content'
        Ignore other POST/PATCH/DELETE operations for the If-Match requirement.
        """
        paths = spec.get("paths") or {}
        for path, item in paths.items():
            if not isinstance(item, dict):
                continue
            for method, op in item.items():
                if not isinstance(op, dict):
                    continue
                m = str(method).lower()
                # Answers autosave PATCH
                if m == "patch" and ("/response-sets/" in path and "/answers/" in path):
                    yield path, m, op
                    continue
                # Documents reorder/content PUT
                if m == "put":
                    if path.endswith("/documents/order"):
                        yield path, m, op
                        continue
                    # Match .../documents/{id}/content with any id placeholder
                    try:
                        import re as _re  # scoped import; tests run in static mode
                        if _re.search(r"/documents/[^/]+/content$", path):
                            yield path, m, op
                            continue
                    except Exception:
                        # If regex is unavailable in runtime, fall back to a simple contains check
                        if "/documents/" in path and path.endswith("/content"):
                            yield path, m, op

    def _has_required_if_match(op: dict, spec: dict) -> bool:
        params = list(op.get("parameters") or [])
        # Direct inline parameter
        for prm in params:
            if not isinstance(prm, dict):
                continue
            name = prm.get("name")
            if name == "If-Match" and prm.get("in") == "header" and bool(prm.get("required")):
                return True
            if "$ref" in prm:
                ref = str(prm["$ref"])  # e.g. #/components/parameters/IfMatch
                if "#/components/parameters/" in ref:
                    comp_name = ref.split("/")[-1]
                    comp = (
                        spec.get("components", {}).get("parameters", {}).get(comp_name, {})
                        if isinstance(spec.get("components"), dict)
                        else {}
                    )
                    if comp.get("name") == "If-Match" and comp.get("in") == "header" and bool(comp.get("required")):
                        return True
        return False

    def _has_problem_json(responses: dict, code: str) -> bool:
        if code not in {str(k) for k in responses.keys()}:
            return False
        # responses may use string or numeric keys
        resp = responses.get(code)
        if resp is None:
            try:
                resp = responses.get(int(code))  # type: ignore[arg-type]
            except Exception:
                resp = None
        if not isinstance(resp, dict):
            return False
        content = resp.get("content") or {}
        return "application/problem+json" in content

    missing: list[str] = []
    for spec in loaded:
        for path, method, op in _iter_operations(spec):
            if not _has_required_if_match(op, spec):
                missing.append(f"{method.upper()} {path} (missing required If-Match)")
                continue
            responses = op.get("responses") or {}
            declared = {str(k) for k in responses.keys()}
            has_428 = "428" in declared
            # Route-specific mismatch status based on path
            route_mismatch: Optional[str] = None
            if "/answers" in path:
                route_mismatch = "409"
            elif "/documents" in path:
                route_mismatch = "412"
            if route_mismatch is None:
                # For non-answers/documents writes, require at least declaration of 428
                if not has_428:
                    missing.append(f"{method.upper()} {path} (missing 428 response)")
                continue
            # Require 428 and the route-specific mismatch status
            if not has_428 or route_mismatch not in declared:
                missing.append(f"{method.upper()} {path} (missing 428 and/or {route_mismatch})")
                continue
            # Require problem+json content for both
            if not _has_problem_json(responses, "428"):
                missing.append(f"{method.upper()} {path} (428 lacks problem+json)")
            if not _has_problem_json(responses, route_mismatch):
                missing.append(f"{method.upper()} {path} ({route_mismatch} lacks problem+json)")
    assert not missing, (
        "Write operations must declare required If-Match and document per-route errors with problem+json: "
        + ", ".join(missing)
    )


# 7.1.22 — Guard uses only public ETag APIs
def test_7_1_22_guard_uses_only_public_etag_apis() -> None:
    """Verifies 7.1.22 — Guard may import only non-private names from app.logic.etag and avoid private attribute access."""
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "Guard module app/guards/precondition.py must exist."
    t = _parse_ast(guard_mod)

    private_imports: list[tuple[int, str]] = []
    for n in ast.walk(t):
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("app.logic.etag"):
            for alias in n.names:
                if alias.name.startswith("_"):
                    private_imports.append((getattr(n, "lineno", -1), alias.name))
    assert not private_imports, (
        "Guard must not import private names from app.logic.etag: "
        + ", ".join([f"line {ln}: {name}" for ln, name in private_imports])
    )

    # Also assert there is no attribute access of private members like etag._foo
    private_attrs: list[tuple[int, str]] = []
    for n in ast.walk(t):
        if isinstance(n, ast.Attribute) and isinstance(n.attr, str) and n.attr.startswith("_"):
            # Record base name if present
            base = None
            if isinstance(n.value, ast.Name):
                base = n.value.id
            elif isinstance(n.value, ast.Attribute):
                base = n.value.attr
            private_attrs.append((getattr(n, "lineno", -1), f"{base or '?'}.{n.attr}"))
    assert not private_attrs, (
        "Guard must not access private attributes of the etag module/helpers: "
        + ", ".join([f"line {ln}: {desc}" for ln, desc in private_attrs])
    )


# 7.1.23 — Diagnostics emitted via central emitter
def test_7_1_23_reorder_diagnostics_emitted_via_emitter() -> None:
    """Verifies 7.1.23 — Reorder diagnostics must be emitted via the shared header emitter."""
    docs_routes = APP_DIR / "routes" / "documents.py"
    assert docs_routes.exists(), "app/routes/documents.py must exist."

    # (1) Assert no direct header assignments to X-List-ETag or X-If-Match-Normalized
    direct_sets = _scan_for_header_sets(docs_routes)
    direct_offenders = [f"line {ln}: {hdr}" for ln, hdr in direct_sets if hdr in {"X-List-ETag", "X-If-Match-Normalized"}]
    assert not direct_offenders, (
        "documents.py must not set diagnostic headers directly; use the emitter: " + ", ".join(direct_offenders)
    )

    # (2) Assert module imports and calls emit_etag_headers
    t = _parse_ast(docs_routes)
    imported_emit = False
    called_emit = False
    for n in ast.walk(t):
        if isinstance(n, ast.ImportFrom) and n.module == "app.logic.header_emitter":
            for alias in n.names:
                if alias.name == "emit_etag_headers":
                    imported_emit = True
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name) and n.func.id == "emit_etag_headers":
                called_emit = True
            if isinstance(n.func, ast.Attribute) and n.func.attr == "emit_etag_headers":
                called_emit = True
    assert imported_emit and called_emit, "documents.py must import and call emit_etag_headers during reorder failure."

    # (3) Assert central emitter references diagnostic headers
    emitter_mod = APP_DIR / "logic" / "header_emitter.py"
    assert emitter_mod.exists(), "app/logic/header_emitter.py must exist."
    emitter_src = emitter_mod.read_text(encoding="utf-8")
    for required in ("X-List-ETag", "X-If-Match-Normalized"):
        assert required in emitter_src, f"header_emitter must reference diagnostic header '{required}'."


# 7.1.24 — CORS allow-list includes If-Match
def test_7_1_24_cors_allow_list_includes_if_match() -> None:
    """Verifies 7.1.24 — CORSMiddleware must allow header 'If-Match' via allow_headers."""
    main_py = APP_DIR / "main.py"
    assert main_py.exists(), "app/main.py must exist."
    t = _parse_ast(main_py)

    found_if_match = False
    for n in ast.walk(t):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_middleware":
            if n.args and (
                (isinstance(n.args[0], ast.Name) and n.args[0].id == "CORSMiddleware")
                or (isinstance(n.args[0], ast.Attribute) and n.args[0].attr == "CORSMiddleware")
            ):
                for kw in n.keywords or []:
                    if kw.arg == "allow_headers" and isinstance(kw.value, (ast.List, ast.Tuple)):
                        values: list[str] = []
                        for elt in kw.value.elts:
                            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                                values.append(elt.value)
                        if "If-Match" in values:
                            found_if_match = True
    assert found_if_match, "CORSMiddleware must include 'If-Match' in allow_headers."


# 7.1.25 — Guard failures include CORS headers
def test_7_1_25_guard_failures_include_cors_headers() -> None:
    """Verifies 7.1.25 — Guard failure handlers set Access-Control-Expose-Headers containing diagnostic names (AST)."""
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "Guard module app/guards/precondition.py must exist."
    try:
        src = guard_mod.read_text(encoding="utf-8")
    except Exception as exc:
        pytest.fail(f"Failed reading guard module for 7.1.25: {exc}")
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        pytest.fail(f"Syntax error parsing guard module for 7.1.25: {exc}")

    # Identify candidate failure-handling functions: those referencing PRE_IF_MATCH_* or 428/409/412
    def _is_failure_handler(fn: ast.FunctionDef) -> bool:
        has_marker = False
        for n in ast.walk(fn):
            if isinstance(n, ast.Constant):
                if isinstance(n.value, str) and (
                    "PRE_IF_MATCH_MISSING" in n.value or "PRE_IF_MATCH_ETAG_MISMATCH" in n.value
                ):
                    has_marker = True
                if isinstance(n.value, int) and n.value in {428, 409, 412}:
                    has_marker = True
            if isinstance(n, ast.Constant) and isinstance(n.value, int) and n.value in {428, 409, 412}:
                has_marker = True
        return has_marker

    failure_fns: list[ast.FunctionDef] = [fn for fn in _function_defs(tree) if _is_failure_handler(fn)]
    assert failure_fns, "Guard must define failure-handling paths constructing problem+json responses."

    # For each candidate, ensure an assignment to headers['Access-Control-Expose-Headers'] includes diagnostic names
    diag_tokens = {"X-List-ETag", "X-If-Match-Normalized"}
    found_expose_with_diag = False

    for fn in failure_fns:
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Subscript):
                        # Ensure target is <something>.headers['Access-Control-Expose-Headers']
                        base = tgt.value
                        is_headers_attr = isinstance(base, ast.Attribute) and base.attr == "headers"
                        sl = getattr(tgt, "slice", None)
                        if isinstance(sl, ast.Index):
                            sl = sl.value
                        key_ok = isinstance(sl, ast.Constant) and isinstance(sl.value, str) and sl.value == "Access-Control-Expose-Headers"
                        if is_headers_attr and key_ok:
                            # Inspect assigned value for diagnostic names within any string/list
                            assigned_has_diag = False
                            for sub in ast.walk(node.value):
                                if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                                    if any(tok in sub.value for tok in diag_tokens):
                                        assigned_has_diag = True
                            if assigned_has_diag:
                                found_expose_with_diag = True
    assert found_expose_with_diag, (
        "Guard failure-handling must set headers['Access-Control-Expose-Headers'] to expose diagnostic headers."
    )


# 7.1.26 — No repository access before guard success
def test_7_1_26_no_repository_access_before_guard_success() -> None:
    """Verifies 7.1.26 — If a mutation route does not mount the guard, its body must not call repository_* before guard."""
    routes_dir = APP_DIR / "routes"
    assert routes_dir.exists(), "app/routes/ directory must exist."

    def _has_guard_in_decorator(fn: ast.FunctionDef) -> bool:
        for dec in fn.decorator_list:
            if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                if dec.func.attr.lower() in {"post", "patch", "delete"}:
                    for kw in dec.keywords or []:
                        if kw.arg == "dependencies" and isinstance(kw.value, (ast.List, ast.Tuple)):
                            for elt in kw.value.elts:
                                if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name) and elt.func.id == "Depends":
                                    if elt.args and isinstance(elt.args[0], ast.Name) and elt.args[0].id == "precondition_guard":
                                        return True
        # Parameter default Depends(precondition_guard)
        for default in list(fn.args.defaults or []) + list(fn.args.kw_defaults or []):  # type: ignore[attr-defined]
            if isinstance(default, ast.Call) and isinstance(default.func, ast.Name) and default.func.id == "Depends":
                if default.args and isinstance(default.args[0], ast.Name) and default.args[0].id == "precondition_guard":
                    return True
        return False

    def _calls_repository(fn: ast.FunctionDef) -> bool:
        # Detect calls to repository_* names or imports from app.logic.repository_*
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                # Direct name call
                if isinstance(node.func, ast.Name) and node.func.id.startswith("repository_"):
                    return True
                # Attribute call like repo.repository_answers.foo or module.repository_answers.foo
                if isinstance(node.func, ast.Attribute) and isinstance(node.func.attr, str):
                    if node.func.attr.startswith("repository_"):
                        return True
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.logic.repository_"):
                return True
        return False

    offenders: list[str] = []
    for py in _iter_py_files(routes_dir):
        t = _parse_ast(py)
        for fn in _function_defs(t):
            # Only consider mutation handlers
            is_mutation = any(
                isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute) and dec.func.attr.lower() in {"post", "patch", "delete"}
                for dec in fn.decorator_list
            )
            if not is_mutation:
                continue
            has_guard = _has_guard_in_decorator(fn)
            if not has_guard and _calls_repository(fn):
                offenders.append(f"{py.name}::{fn.name}")
    assert not offenders, (
        "Mutation handlers without precondition_guard must not access repositories before guard success: "
        + ", ".join(offenders)
    )
