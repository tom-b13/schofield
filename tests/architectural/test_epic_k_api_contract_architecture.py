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


def _function_defs(node: ast.AST) -> list[Any]:
    """Return both sync and async function definitions within an AST tree.

    This helper intentionally returns a heterogeneous list to allow callers to
    iterate over both ast.FunctionDef and ast.AsyncFunctionDef nodes.
    """
    return [
        n
        for n in ast.walk(node)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


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
    etag_mod = APP_DIR / "logic" / "etag.py"
    assert etag_mod.exists(), "app/logic/etag.py must exist."
    tree = _parse_ast(etag_mod)
    normalisers: list[str] = []
    for n in getattr(tree, "body", []):
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_"):
            if re.search(r"normalis|normaliz|normalize|normalise", n.name, re.IGNORECASE):
                normalisers.append(n.name)
    assert len(normalisers) == 1, (
        "Exactly one exported If-Match normaliser must be defined in app/logic/etag.py; "
        f"found {normalisers}"
    )
    normaliser_name = normalisers[0]

    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "Guard module app/guards/precondition.py must exist."
    gtree = _parse_ast(guard_mod)

    imported_aliases: set[str] = set()
    for n in ast.walk(gtree):
        if isinstance(n, ast.ImportFrom) and (n.module or "") == "app.logic.etag":
            for alias in n.names:
                if alias.name == normaliser_name:
                    imported_aliases.add(alias.asname or alias.name)
    assert imported_aliases, (
        f"Guard must import '{normaliser_name}' from app.logic.etag via ImportFrom."
    )

    called = False
    for n in ast.walk(gtree):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name) and n.func.id in imported_aliases:
                called = True
            if isinstance(n.func, ast.Attribute) and n.func.attr in imported_aliases:
                called = True
    assert called, (
        f"Guard must invoke the imported If-Match normaliser '{normaliser_name}'."
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

    offenders: list[str] = []
    # Scope enforcement to Epic K routes only
    scope_modules = {"answers.py", "documents.py", "screens.py", "authoring_screens.py", "authoring_questions.py"}
    for py in (APP_DIR / "routes").glob("*.py"):
        if py.name not in scope_modules:
            continue
        if py.name in {"test_support.py"}:
            continue
        t = _parse_ast(py)
        imported_emit = False
        for n in ast.walk(t):
            if isinstance(n, ast.ImportFrom) and n.module == "app.logic.header_emitter":
                for alias in n.names:
                    if alias.name == "emit_etag_headers":
                        imported_emit = True
        for fn in _function_defs(t):
            has_route_decorator = any(
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr.lower() in {"post", "patch", "delete"}
                for dec in fn.decorator_list
            )
            if not has_route_decorator:
                continue
            called_emit = False
            for node in ast.walk(fn):
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name) and node.func.id == "emit_etag_headers":
                        called_emit = True
                    if isinstance(node.func, ast.Attribute) and node.func.attr == "emit_etag_headers":
                        called_emit = True
            if not (imported_emit and called_emit):
                offenders.append(f"{py.name}::{fn.name}")

        # Ban direct header sets in scoped route files
        for (_lineno, hdr) in _scan_for_header_sets(py):
            if hdr in {"ETag", "Screen-ETag", "Question-ETag", "Questionnaire-ETag", "Document-ETag"}:
                offenders.append(f"direct header set {hdr} in {py.name}")
    assert not offenders, (
        "All mutation handlers must call the central emitter; direct header sets are forbidden: "
        + ", ".join(offenders)
    )


# 7.1.6 — Scope→header mapping centralised
def test_7_1_6_scope_to_header_mapping_centralised() -> None:
    """Asserts a single centralised scope→header mapping is reused (7.1.6)."""
    # Verifies section 7.1.6
    logic_dir = APP_DIR / "logic"
    assert logic_dir.exists(), "app/logic directory must exist."

    domain_headers = {"Screen-ETag", "Question-ETag", "Questionnaire-ETag", "Document-ETag"}

    # Discover exactly one module-scope dict with keys {'screen','question','questionnaire','document'}
    # and values that include the four domain header names. Name-agnostic.
    candidates: list[tuple[Path, str]] = []  # (file, var_name)
    for py in logic_dir.glob("*.py"):
        t = _parse_ast(py)
        for n in getattr(t, "body", []):
            if isinstance(n, ast.Assign):
                target_names = [tg.id for tg in n.targets if isinstance(tg, ast.Name)]
                if not target_names:
                    continue
                if not isinstance(n.value, ast.Dict):
                    continue
                key_literals: list[str] = []
                val_literals: list[str] = []
                for k in n.value.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        key_literals.append(k.value)
                for v in n.value.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str):
                        val_literals.append(v.value)
                if set(key_literals) == {"screen", "question", "questionnaire", "document"}:
                    if domain_headers.issubset(set(val_literals)):
                        # Record each simple name target as a candidate mapping symbol
                        for name in target_names:
                            candidates.append((py, name))

    assert len(candidates) == 1, (
        "Exactly one central scope→header mapping (by content) must exist under app/logic/. "
        f"Found {len(candidates)} candidates: " + ", ".join(f"{p.name}:{n}" for p, n in candidates)
    )

    mapping_file, mapping_name = candidates[0]

    # Assert header_emitter.py references that mapping (either defined inline or via import/name/attribute)
    emitter_mod = APP_DIR / "logic" / "header_emitter.py"
    assert emitter_mod.exists(), "app/logic/header_emitter.py must exist."
    if emitter_mod == mapping_file:
        emitter_references_mapping = True  # mapping is defined in emitter itself
    else:
        et = _parse_ast(emitter_mod)
        emitter_references_mapping = False
        for node in ast.walk(et):
            # Direct name usage implies it was imported with `from ... import <name>`
            if isinstance(node, ast.Name) and node.id == mapping_name:
                emitter_references_mapping = True
                break
            # Attribute usage implies `import module as m` then `m.<name>`
            if isinstance(node, ast.Attribute) and node.attr == mapping_name:
                emitter_references_mapping = True
                break
        assert emitter_references_mapping, (
            "header_emitter.py must reference the central scope→header mapping (by Name or Attribute)."
        )

    # Assert callers do not hard-code domain header names directly in header-setting contexts
    hardcoded_offenders: list[str] = []
    for py in (APP_DIR / "routes").glob("*.py"):
        if py == emitter_mod:
            continue
        t = _parse_ast(py)
        # headers['Domain'] = ...
        for n in ast.walk(t):
            if isinstance(n, ast.Assign):
                for tgt in n.targets:
                    if isinstance(tgt, ast.Subscript) and isinstance(tgt.value, ast.Attribute) and tgt.value.attr == "headers":
                        sl = getattr(tgt, "slice", None)
                        if isinstance(sl, ast.Index):
                            sl = sl.value
                        if isinstance(sl, ast.Constant) and isinstance(sl.value, str) and sl.value in domain_headers:
                            hardcoded_offenders.append(f"{py.name} sets headers['{sl.value}'] directly")
        # headers.update({ 'Domain': ... })
        for n in ast.walk(t):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "update":
                base = n.func.value
                if isinstance(base, ast.Attribute) and base.attr == "headers":
                    for arg in n.args:
                        if isinstance(arg, ast.Dict):
                            for k in arg.keys:
                                if isinstance(k, ast.Constant) and isinstance(k.value, str) and k.value in domain_headers:
                                    hardcoded_offenders.append(f"{py.name} updates headers with '{k.value}' directly")
        # headers.__setitem__('Domain', ...)
        for n in ast.walk(t):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "__setitem__":
                base = n.func.value
                if isinstance(base, ast.Attribute) and base.attr == "headers":
                    if n.args and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str) and n.args[0].value in domain_headers:
                        hardcoded_offenders.append(f"{py.name} __setitem__ headers '{n.args[0].value}' directly")
    assert not hardcoded_offenders, (
        "Domain header names must not be hard-coded in route modules (only emitter may use mapping): "
        + ", ".join(hardcoded_offenders)
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
        ref = str(prop["$ref"]).lower()
        ok = ("etag" in ref) and ("schema" in ref or "#/components/schemas/" in ref)
        assert ok, f"headers.{key} $ref must point to an ETag token schema, got: {prop['$ref']}"

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

    # Assert unchanged baseline entry points (superset allowed)
    missing = sorted(baseline - exported)
    assert not missing, (
        "app/logic/etag.py public API must retain baseline entry points. Missing: "
        + ", ".join(missing)
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

    # Assert: at least one function body contains a lazy import of ETag helpers
    found_lazy_etag_import = False
    for fn in _function_defs(t):
        for node in fn.body:
            for sub in ast.walk(node):
                if isinstance(sub, ast.ImportFrom) and (sub.module or "").startswith("app.logic.etag"):
                    found_lazy_etag_import = True
                if isinstance(sub, ast.Import):
                    for alias in sub.names:
                        if alias.name.startswith("app.logic.etag"):
                            found_lazy_etag_import = True
    assert found_lazy_etag_import, (
        "Guard must locally import ETag helpers (Import/ImportFrom) inside function scope(s)."
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

    # Note: Per AGENTS.md 4.4 and Clarke's review, architectural tests must
    # remain AST/static-only. Do not import or execute application modules here.


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
    """Verifies 7.1.20 — Central mapping exists and guard imports it (missing→428; mismatch answers→409; mismatch documents→412)."""
    # 1) Central mapping module exists and has required shape (static AST only)
    mapping_mod = APP_DIR / "config" / "error_mapping.py"
    assert mapping_mod.exists(), "Mapping module app/config/error_mapping.py must exist."
    mtree = _parse_ast(mapping_mod)
    found_map = False
    required = {
        "missing": {"code": "PRE_IF_MATCH_MISSING", "status": 428},
        "mismatch_answers": {"code": "PRE_IF_MATCH_ETAG_MISMATCH", "status": 409},
        "mismatch_documents": {"code": "PRE_IF_MATCH_ETAG_MISMATCH", "status": 412},
    }
    for n in getattr(mtree, "body", []):
        if isinstance(n, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "PRECONDITION_ERROR_MAP" for t in n.targets) and isinstance(n.value, ast.Dict):
                keys: list[str] = []
                vals: list[dict] = []
                for k, v in zip(n.value.keys, n.value.values):
                    if isinstance(k, ast.Constant) and isinstance(k.value, str) and isinstance(v, ast.Dict):
                        entry: dict[str, Any] = {}
                        for kk, vv in zip(v.keys, v.values):
                            if isinstance(kk, ast.Constant) and isinstance(kk.value, str):
                                if isinstance(vv, ast.Constant):
                                    entry[kk.value] = vv.value
                        keys.append(k.value)
                        vals.append(entry)
                mp = dict(zip(keys, vals))
                for k, expected in required.items():
                    assert k in mp, f"PRECONDITION_ERROR_MAP missing key '{k}'"
                    got = mp[k]
                    assert got.get("code") == expected["code"], f"{k}.code must be {expected['code']}"
                    assert int(got.get("status", -1)) == expected["status"], f"{k}.status must be {expected['status']}"
                found_map = True
    assert found_map, "PRECONDITION_ERROR_MAP literal dict assignment not found with required shape."

    # 2) Guard imports the central mapping (no hardcoded literals asserted here)
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "Guard module app/guards/precondition.py must exist."
    tree = _parse_ast(guard_mod)
    # Verify import of PRECONDITION_ERROR_MAP from app.config.error_mapping
    imported = False
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom):
            if (getattr(n, "module", "") == "app.config.error_mapping"):
                for alias in n.names:
                    if alias.name == "PRECONDITION_ERROR_MAP":
                        imported = True
    assert imported, "Guard must import PRECONDITION_ERROR_MAP from app.config.error_mapping"

    # Optional negative check: discourage hardcoding of code strings and status ints in guard
    # Allow presence in comments/docstrings or in non-precondition branches.
    # Here we only ensure the mapping is the intended source of truth, not enforce a full ban.


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
        """Yield all in-scope write operations (answers/documents, POST|PUT|PATCH|DELETE)."""
        paths = spec.get("paths") or {}
        for path, item in paths.items():
            if not isinstance(item, dict):
                continue
            in_scope = ("/answers" in path) or ("/documents" in path)
            if not in_scope:
                continue
            for method, op in item.items():
                if not isinstance(op, dict):
                    continue
                m = str(method).lower()
                if m in {"post", "put", "patch", "delete"}:
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

    # Also assert there is no attribute access of private etag members; scope to etag imports only
    etag_aliases: set[str] = set()
    for n in ast.walk(t):
        if isinstance(n, ast.Import):
            for alias in n.names:
                if alias.name == "app.logic.etag":
                    etag_aliases.add(alias.asname or alias.name or "etag")
                if alias.name.startswith("app.logic.etag."):
                    etag_aliases.add(alias.asname or alias.name.rsplit(".", 1)[-1])
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("app.logic.etag"):
            # ImportFrom of specific functions: collect names for attribute chain checks
            for alias in n.names:
                etag_aliases.add(alias.asname or alias.name)

    private_attrs: list[tuple[int, str]] = []
    for n in ast.walk(t):
        if isinstance(n, ast.Attribute) and isinstance(n.attr, str) and n.attr.startswith("_"):
            base_ok = False
            if isinstance(n.value, ast.Name) and n.value.id in etag_aliases:
                base_ok = True
            if isinstance(n.value, ast.Attribute) and isinstance(n.value.attr, str) and n.value.attr in etag_aliases:
                base_ok = True
            if base_ok:
                base = None
                if isinstance(n.value, ast.Name):
                    base = n.value.id
                elif isinstance(n.value, ast.Attribute):
                    base = n.value.attr
                private_attrs.append((getattr(n, "lineno", -1), f"{base or '?'}.{n.attr}"))
    assert not private_attrs, (
        "Guard must not access private attributes of app.logic.etag via its imported aliases: "
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
    # Apply repository-before-guard rule only to answers/documents write routes (Phase-0 scope)
    allowed = {"answers.py", "documents.py"}
    for py in _iter_py_files(routes_dir):
        if py.name not in allowed:
            continue
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


# 7.1.29 — Global Problem+JSON handlers are registered in create_app
def test_7_1_29_global_problem_json_handlers_registered_in_create_app() -> None:
    """Verifies 7.1.29 — create_app defines exception handlers using allowed problem modules (static AST)."""
    # Verifies section 7.1.29
    main_py = APP_DIR / "main.py"
    assert main_py.exists(), "app/main.py must exist."
    t = _parse_ast(main_py)

    # Locate create_app function
    fns = [fn for fn in _function_defs(t) if fn.name == "create_app"]
    assert fns, "app/main.py must define create_app()"
    fn = fns[0]

    # Map imported handler names to their source modules for allowlist validation
    allowed_modules = {"app.http.problem", "app.http.errors"}
    import_map: dict[str, str] = {}
    for n in ast.walk(t):
        if isinstance(n, ast.ImportFrom) and n.module in allowed_modules:
            for alias in n.names:
                import_map[alias.asname or alias.name] = n.module  # symbol -> module

    # Within create_app, assert calls to add_exception_handler for specific exception types
    expected_exceptions = {"HTTPException", "RequestValidationError", "Exception"}
    seen: set[str] = set()
    handler_from_allowed = False
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_exception_handler":
            args = list(n.args)
            if not args:
                continue
            exc_name = None
            if isinstance(args[0], ast.Name):
                exc_name = args[0].id
            elif isinstance(args[0], ast.Attribute):
                exc_name = args[0].attr
            if exc_name:
                seen.add(exc_name)
            if len(args) >= 2:
                handler = args[1]
                if isinstance(handler, ast.Name) and handler.id in import_map and import_map[handler.id] in allowed_modules:
                    handler_from_allowed = True
                if isinstance(handler, ast.Attribute) and isinstance(handler.value, ast.Name):
                    base = handler.value.id
                    if base in import_map and import_map[base] in allowed_modules:
                        handler_from_allowed = True

    missing = sorted(expected_exceptions - seen)
    assert not missing, (
        "create_app must register exception handlers for HTTPException, RequestValidationError, and Exception"
    )
    assert handler_from_allowed, (
        "Exception handlers must originate from allowed problem modules (app.http.problem/errors)."
    )

    # Also assert problem module declares PROBLEM_MEDIA_TYPE constant
    problem_mod = APP_DIR / "http" / "problem.py"
    assert problem_mod.exists(), "app/http/problem.py must exist and expose PROBLEM_MEDIA_TYPE."
    ptree = _parse_ast(problem_mod)
    has_const = False
    for n in getattr(ptree, "body", []):
        if isinstance(n, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "PROBLEM_MEDIA_TYPE" for t in n.targets):
                if isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                    has_const = True
    assert has_const, "app/http/problem.py must define string constant PROBLEM_MEDIA_TYPE."


# 7.1.30 — Request ID middleware is registered at app startup
def test_7_1_30_request_id_middleware_registered_once() -> None:
    """Verifies 7.1.30 — create_app adds exactly one RequestIdMiddleware (static AST)."""
    # Verifies section 7.1.30
    main_py = APP_DIR / "main.py"
    assert main_py.exists(), "app/main.py must exist."
    t = _parse_ast(main_py)
    fns = [fn for fn in _function_defs(t) if fn.name == "create_app"]
    assert fns, "app/main.py must define create_app()"
    fn = fns[0]

    add_calls = 0
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "add_middleware":
            if n.args:
                arg0 = n.args[0]
                if isinstance(arg0, ast.Name) and arg0.id == "RequestIdMiddleware":
                    add_calls += 1
                if isinstance(arg0, ast.Attribute) and arg0.attr == "RequestIdMiddleware":
                    add_calls += 1
    assert add_calls == 1, "create_app must register exactly one RequestIdMiddleware."

    # Ensure not imported from tests.* modules
    for n in ast.walk(t):
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("tests."):
            for alias in n.names:
                if alias.name == "RequestIdMiddleware":
                    pytest.fail("RequestIdMiddleware must not be imported from tests.* modules.")


# 7.1.31 — No test-coupled fallbacks or harness leakage in repositories and guard
def test_7_1_31_no_test_coupled_fallbacks_in_repos_and_guard() -> None:
    """Verifies 7.1.31 — No hardcoded test ids/UUID fallbacks or test harness leakage (AST + targeted regex)."""
    # Verifies section 7.1.31
    targets: list[Path] = []
    targets += list((APP_DIR / "logic").glob("repository_*.py"))
    targets.append(APP_DIR / "guards" / "precondition.py")
    for extra in ["etag.py", "screen_builder.py", "header_emitter.py"]:
        p = APP_DIR / "logic" / extra
        if p.exists():
            targets.append(p)

    uuid_re = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
    special_literals = {"q_001", "section_17_36", "invoke_orchestrator_trace", "X-EpicK-ForceError", "force_error"}

    violations: list[str] = []

    for path in targets:
        if not path.exists():
            continue
        t = _parse_ast(path)
        src = path.read_text(encoding="utf-8")

        # (1) No dict with string keys matching UUID or "q_001"
        for n in ast.walk(t):
            if isinstance(n, ast.Dict):
                for k in n.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        if uuid_re.match(k.value) or k.value == "q_001":
                            violations.append(f"{path.name}: dict key '{k.value}' looks like test-coupled id")

        # (2) No constant test-id strings in return expressions or equality comparisons
        for n in ast.walk(t):
            if isinstance(n, ast.Return):
                val = n.value
                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                    if uuid_re.match(val.value) or val.value == "q_001":
                        violations.append(f"{path.name}: returns hardcoded id '{val.value}'")
                if isinstance(val, ast.JoinedStr):
                    for p2 in val.values:
                        if isinstance(p2, ast.Constant) and isinstance(p2.value, str):
                            if re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", p2.value) or ("q_001" in p2.value):
                                violations.append(f"{path.name}: f-string in return contains test id literal")
            if isinstance(n, ast.Compare):
                comparands = [n.left] + list(n.comparators)
                for c in comparands:
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        if uuid_re.match(c.value) or c.value == "q_001":
                            violations.append(f"{path.name}: comparison uses test id '{c.value}'")

        # (3) No imports from tests.* and no forbidden symbol references
        for n in ast.walk(t):
            if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("tests."):
                violations.append(f"{path.name}: imports from tests.* not allowed")
            if isinstance(n, ast.Import):
                for alias in n.names:
                    if alias.name.startswith("tests."):
                        violations.append(f"{path.name}: imports from tests.* not allowed")
            if isinstance(n, ast.Name) and n.id in special_literals:
                violations.append(f"{path.name}: forbidden symbol reference '{n.id}'")
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in special_literals:
                violations.append(f"{path.name}: forbidden literal '{n.value}'")

        # (4) Secondary regex scan for behavioural contexts
        for line in src.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("return") or "= f\"" in stripped or "= f'" in stripped:
                if re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", stripped):
                    violations.append(f"{path.name}: potential UUID literal in behavioural context")
                if "q_001" in stripped:
                    violations.append(f"{path.name}: 'q_001' literal in behavioural context")

    assert not violations, (
        "Production code must not embed test-coupled ids or harness hooks; replace with real lookups or move to fixtures. "
        + ", ".join(violations)
    )


# 7.1.32 — Guard enforces first-failure precedence for write routes
def test_7_1_32_guard_enforces_first_failure_precedence() -> None:
    """Verifies 7.1.32 — Guard calls helpers in order and supports early-return/raise; no success header sets in guard."""
    # Verifies section 7.1.32
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "Guard module app/guards/precondition.py must exist."
    tree = _parse_ast(guard_mod)

    # Locate precondition_guard function
    guard_fns = [fn for fn in _function_defs(tree) if fn.name == "precondition_guard"]
    assert guard_fns, "precondition_guard function must be defined."
    gf = guard_fns[0]

    # (1) Verify call order of helpers
    required_order = [
        "_check_content_type",
        "_check_if_match_presence",
        "_parse_if_match",
        "_compare_etag",
    ]
    first_index: dict[str, int] = {}
    linear_nodes: list[ast.AST] = list(ast.walk(gf))
    for idx, node in enumerate(linear_nodes):
        if isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in required_order and name not in first_index:
                first_index[name] = idx
    missing = [n for n in required_order if n not in first_index]
    assert not missing, f"Guard must call helper(s) in order; missing: {missing}"
    # Assert increasing order of first occurrences
    indices = [first_index[n] for n in required_order]
    assert indices == sorted(indices), (
        "Guard must call helpers in source order: " + ", ".join(required_order)
    )

    # (2) Early-return or raise present between each check
    def _has_early_exit(start: int, end: int) -> bool:
        for node in linear_nodes[start:end]:
            if isinstance(node, (ast.Raise, ast.Return)):
                return True
        return False

    for i in range(len(required_order) - 1):
        a, b = required_order[i], required_order[i + 1]
        if a in first_index and b in first_index:
            assert _has_early_exit(first_index[a], first_index[b]), (
                f"Expected an early exit (return/raise) after {a} before {b} in guard."
            )

    # (3) Guard must not set success headers or call emit_etag_headers
    domain_headers = {"ETag", "Screen-ETag", "Question-ETag", "Questionnaire-ETag", "Document-ETag"}
    offenders = []
    for lineno, header_name in _scan_for_header_sets(guard_mod):
        if header_name in domain_headers:
            offenders.append(f"line {lineno}: headers['{header_name}'] assignment in guard")
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "emit_etag_headers":
                offenders.append("emit_etag_headers() called in guard")
            if isinstance(node.func, ast.Attribute) and node.func.attr == "emit_etag_headers":
                offenders.append("emit_etag_headers() called in guard")
    assert not offenders, (
        "Guard must not emit success headers: " + ", ".join(offenders)
    )


# 7.1.33 — Content-Type 415 enforced in guard prior to body parsing
def test_7_1_33_guard_enforces_content_type_415_prior_to_body_parsing() -> None:
    """Verifies 7.1.33 — Guard checks Content-Type and rejects with 415 before any body parsing; app/http must not perform If-Match or PRE_* logic."""
    # Verifies section 7.1.33
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "Guard module app/guards/precondition.py must exist."
    tree = _parse_ast(guard_mod)

    # Locate precondition_guard function
    guard_fns = [fn for fn in _function_defs(tree) if fn.name == "precondition_guard"]
    assert guard_fns, "precondition_guard function must be defined."
    gf = guard_fns[0]

    # Gather indices of Content-Type/415 markers and body parsing calls in traversal order
    nodes = list(ast.walk(gf))
    ctype_indices: list[int] = []
    json_parse_indices: list[int] = []
    for idx, n in enumerate(nodes):
        if isinstance(n, ast.Constant) and isinstance(n.value, (str, int)):
            if (isinstance(n.value, str) and ("Content-Type" in n.value or "Unsupported Media Type" in n.value)) or (
                isinstance(n.value, int) and n.value == 415
            ):
                ctype_indices.append(idx)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in {"json", "model_validate", "parse_obj"}:
            json_parse_indices.append(idx)
    assert ctype_indices, "Guard must contain a Content-Type check and 415 mapping."
    if json_parse_indices:
        assert min(ctype_indices) < min(json_parse_indices), (
            "Content-Type 415 must be enforced before body parsing/validation calls."
        )

    # app/http must not perform If-Match checks or PRE_* emissions
    http_dir = APP_DIR / "http"
    assert http_dir.exists(), "app/http directory must exist."
    http_offenders: list[str] = []
    for py in _iter_py_files(http_dir):
        t = _parse_ast(py)
        # No import of guard
        for n in ast.walk(t):
            if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("app.guards"):
                for alias in n.names:
                    if alias.name == "precondition_guard":
                        http_offenders.append(f"{py.name} imports precondition_guard")
        # No PRE_* string constants in app/http
        for n in ast.walk(t):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("PRE_"):
                http_offenders.append(f"{py.name} contains PRE_* constant '{n.value}'")
        # No explicit If-Match header usage
        for n in ast.walk(t):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value == "If-Match":
                http_offenders.append(f"{py.name} references If-Match header")
    assert not http_offenders, (
        "app/http wrappers must not perform If-Match checks or PRE_* emissions: " + ", ".join(http_offenders)
    )


# 7.1.34 — No normalise or compare ETag in routes or wrappers
def test_7_1_34_no_normalise_or_compare_etag_in_routes_or_wrappers() -> None:
    """Verifies 7.1.34 — Only guard may import/use ETag normaliser/comparison; routes/http must not raise PRE_* types."""
    routes_dir = APP_DIR / "routes"
    http_dir = APP_DIR / "http"
    assert routes_dir.exists(), "app/routes directory must exist."
    assert http_dir.exists(), "app/http directory must exist."

    offenders: list[str] = []
    # (1) No imports of normaliser/comparison in routes or wrappers
    def _scan_file_for_etag_imports(path: Path) -> None:
        t = _parse_ast(path)
        for n in ast.walk(t):
            if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("app.logic.etag"):
                for alias in n.names:
                    if re.search(r"normalis|normaliz|normalize|normalise|compare", alias.name, re.IGNORECASE):
                        offenders.append(f"{path.name}: imports {alias.name} from app.logic.etag")
            if isinstance(n, ast.Import) and any(m.name.startswith("app.logic.etag") for m in n.names):
                offenders.append(f"{path.name}: imports app.logic.etag module")
        # (3) No PRE_* problem types raised in routes/wrappers
        for n in ast.walk(t):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("PRE_"):
                offenders.append(f"{path.name}: contains PRE_* constant '{n.value}'")

    for py in _iter_py_files(routes_dir):
        _scan_file_for_etag_imports(py)
    for py in _iter_py_files(http_dir):
        _scan_file_for_etag_imports(py)

    # (2) Only guard may import/use the normaliser/comparison
    guard_path = APP_DIR / "guards" / "precondition.py"
    assert guard_path.exists(), "Guard module must exist."
    guard_tree = _parse_ast(guard_path)
    guard_has_etag_use = False
    for n in ast.walk(guard_tree):
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("app.logic.etag"):
            guard_has_etag_use = True
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name) and re.search(r"normalis|normaliz|normalize|normalise|compare", n.func.id, re.IGNORECASE):
                guard_has_etag_use = True
            if isinstance(n.func, ast.Attribute) and re.search(r"normalis|normaliz|normalize|normalise|compare", n.func.attr, re.IGNORECASE):
                guard_has_etag_use = True
    assert guard_has_etag_use, "Guard must be the only place using ETag normaliser/comparison."

    assert not offenders, (
        "Routes/wrappers must not import/use ETag normaliser or PRE_* constants: " + ", ".join(offenders)
    )


# 7.1.35 — Canonical PRE_* mapping includes invalid-format and route-kind split
def test_7_1_35_canonical_pre_mapping_includes_invalid_format_and_route_kind_split() -> None:
    """Verifies 7.1.35 — error mapping defines missing→428, invalid-format→409, mismatch split (answers→409, documents→412); guard/wrappers do not use RUN_* in failures."""
    mapping_py = APP_DIR / "config" / "error_mapping.py"
    assert mapping_py.exists(), "app/config/error_mapping.py must exist."
    tree = _parse_ast(mapping_py)

    # Find PRECONDITION_ERROR_MAP dict literal
    maps: list[ast.Dict] = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "PRECONDITION_ERROR_MAP" for t in n.targets) and isinstance(n.value, ast.Dict):
                maps.append(n.value)
    assert maps, "PRECONDITION_ERROR_MAP must be defined as a dict literal."
    m = maps[0]

    def _dict_to_py(d: ast.Dict) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in zip(d.keys, d.values):
            if isinstance(k, ast.Constant) and isinstance(k.value, str):
                key = k.value
            else:
                continue
            if isinstance(v, ast.Dict):
                entry: dict[str, Any] = {}
                for kk, vv in zip(v.keys, v.values):
                    if isinstance(kk, ast.Constant) and isinstance(kk.value, str):
                        if isinstance(vv, ast.Constant):
                            entry[kk.value] = vv.value
                out[key] = entry
        return out

    pm = _dict_to_py(m)
    # (1) Missing → 428 with code PRE_IF_MATCH_MISSING
    miss = pm.get("missing") or pm.get("absent")
    assert miss and miss.get("status") == 428 and miss.get("code") == "PRE_IF_MATCH_MISSING", (
        "Mapping must define missing→428 with PRE_IF_MATCH_MISSING."
    )
    # (2) Invalid format → 409
    inv = pm.get("invalid_format") or pm.get("invalid")
    assert inv and inv.get("status") == 409 and inv.get("code") == "PRE_IF_MATCH_INVALID_FORMAT", (
        "Mapping must define invalid_format→409 with PRE_IF_MATCH_INVALID_FORMAT."
    )
    # (3) Mismatch split: answers/screens→409; documents reorder→412
    ans = pm.get("mismatch_answers") or pm.get("answers")
    docs = pm.get("mismatch_documents") or pm.get("documents")
    assert ans and ans.get("status") == 409 and ans.get("code") == "PRE_IF_MATCH_ETAG_MISMATCH", (
        "Mapping must define answers mismatch→409."
    )
    assert docs and docs.get("status") == 412 and docs.get("code") == "PRE_IF_MATCH_ETAG_MISMATCH", (
        "Mapping must define documents mismatch→412."
    )

    # (4) Guard/wrappers must not reference RUN_* in failure branches
    forbidden_tokens = []
    for path in [APP_DIR / "guards" / "precondition.py"] + list(_iter_py_files(APP_DIR / "http")):
        t = _parse_ast(path)
        for n in ast.walk(t):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("RUN_"):
                forbidden_tokens.append(f"{path.name} contains '{n.value}'")
    assert not forbidden_tokens, (
        "Guard/wrappers must not use RUN_* in failure branches: " + ", ".join(forbidden_tokens)
    )


# 7.1.36 — Reorder diagnostics emitted through header emitter
def test_7_1_36_reorder_diagnostics_via_emitter() -> None:
    """Verifies 7.1.36 — Reorder failure path uses header emitter and does not set diagnostic headers directly."""
    docs_py = APP_DIR / "routes" / "documents.py"
    assert docs_py.exists(), "app/routes/documents.py must exist."
    t = _parse_ast(docs_py)

    # Find reorder handler function
    fns = [fn for fn in _function_defs(t) if fn.name == "put_documents_order"]
    assert fns, "documents.put_documents_order must be defined."
    fn = fns[0]

    # (1) Assert a call to header emitter exists within the handler
    called_emitter = False
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name) and n.func.id in {"emit_etag_headers", "emit_reorder_diagnostics"}:
                called_emitter = True
            if isinstance(n.func, ast.Attribute) and n.func.attr in {"emit_etag_headers", "emit_reorder_diagnostics"}:
                called_emitter = True
    assert called_emitter, (
        "Reorder handler must call a central header emitter (emit_etag_headers or emit_reorder_diagnostics)."
    )

    # (2) Assert no direct set of diagnostic headers in the handler
    direct_sets = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Assign):
            for tgt in n.targets:
                if isinstance(tgt, ast.Subscript):
                    base = tgt.value
                    sl = getattr(tgt, "slice", None)
                    if isinstance(sl, ast.Index):
                        sl = sl.value
                    if (
                        isinstance(base, ast.Attribute)
                        and base.attr == "headers"
                        and isinstance(sl, ast.Constant)
                        and isinstance(sl.value, str)
                        and sl.value in {"X-List-ETag", "X-If-Match-Normalized"}
                    ):
                        direct_sets.append(sl.value)
    assert not direct_sets, (
        "Reorder handler must not set diagnostic headers directly: " + ", ".join(direct_sets)
    )


# 7.1.37 — Write routes avoid signature-level body models
def test_7_1_37_write_routes_avoid_signature_level_body_models() -> None:
    """Verifies 7.1.37 — No Pydantic models/Body(...) in write signatures; request param exists; parsing not before guard."""
    # Verifies section 7.1.37
    route_files = [APP_DIR / "routes" / "answers.py", APP_DIR / "routes" / "documents.py"]

    def _pydantic_model_names(module_path: Path) -> set[str]:
        names: set[str] = set()
        t = _parse_ast(module_path)
        for n in ast.walk(t):
            if isinstance(n, ast.ClassDef):
                # Identify BaseModel subclasses
                for b in n.bases:
                    if isinstance(b, ast.Name) and b.id == "BaseModel":
                        names.add(n.name)
                    if isinstance(b, ast.Attribute) and b.attr == "BaseModel":
                        names.add(n.name)
        return names

    offenders_sig: list[str] = []  # (1) Pydantic or Body(...) in signature
    offenders_req: list[str] = []  # (2) Missing request param
    offenders_parse_before_guard: list[str] = []  # (3) Parsing helpers used but guard not mounted on decorator

    parsing_attrs = {"json", "model_validate", "parse_obj", "parse_raw"}

    for py in route_files:
        assert py.exists(), f"Route module missing: {py}"
        t = _parse_ast(py)
        model_names = _pydantic_model_names(py)

        for fn in _function_defs(t):
            # Consider only write routes
            methods: set[str] = set()
            mounted_guard = False
            for dec in fn.decorator_list:
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    methods.add(dec.func.attr.lower())
                    for kw in dec.keywords or []:
                        if kw.arg == "dependencies" and isinstance(kw.value, (ast.List, ast.Tuple)):
                            for elt in kw.value.elts:
                                if isinstance(elt, ast.Call) and isinstance(elt.func, ast.Name) and elt.func.id == "Depends":
                                    if elt.args and isinstance(elt.args[0], ast.Name) and elt.args[0].id == "precondition_guard":
                                        mounted_guard = True
            if not any(m in {"post", "patch", "delete", "put"} for m in methods):
                continue

            # (1) Detect Pydantic model parameters and Body(...) defaults
            has_bad_sig = False
            # Combine all arg types (positional, posonly, kwonly)
            all_args: list[ast.arg] = []
            all_args.extend(fn.args.args)
            all_args.extend(getattr(fn.args, "posonlyargs", []))  # type: ignore[arg-type]
            all_args.extend(fn.args.kwonlyargs)
            # Defaults for positional args
            pos_defaults = list(fn.args.defaults)
            pos_default_start = len(fn.args.args) - len(pos_defaults)
            for idx, arg in enumerate(all_args):
                default_node = None
                if arg in fn.args.args and idx >= pos_default_start and idx - pos_default_start < len(pos_defaults):
                    default_node = pos_defaults[idx - pos_default_start]
                if arg in fn.args.kwonlyargs:
                    i2 = fn.args.kwonlyargs.index(arg)
                    if i2 < len(fn.args.kw_defaults):
                        default_node = fn.args.kw_defaults[i2]
                if isinstance(default_node, ast.Call) and isinstance(default_node.func, ast.Name) and default_node.func.id == "Body":
                    has_bad_sig = True
                ann = arg.annotation
                if isinstance(ann, ast.Name) and ann.id in model_names:
                    has_bad_sig = True
                if isinstance(ann, ast.Attribute) and ann.attr in model_names:
                    has_bad_sig = True
            if has_bad_sig:
                offenders_sig.append(f"{py.name}::{fn.name}")

            # (2) Ensure a `request` parameter is present by name
            if not any(isinstance(a, ast.arg) and a.arg == "request" for a in fn.args.args):
                offenders_req.append(f"{py.name}::{fn.name}")

            # (3) If parsing helpers are called, ensure guard is mounted via decorator
            uses_parsing = False
            for node in ast.walk(fn):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in parsing_attrs:
                    uses_parsing = True
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"model_validate", "parse_obj", "parse_raw"}:
                    uses_parsing = True
            if uses_parsing and not mounted_guard:
                offenders_parse_before_guard.append(f"{py.name}::{fn.name}")

    assert not offenders_sig, (
        "Write route signatures must not declare Pydantic models or Body(...): "
        + ", ".join(offenders_sig)
    )
    assert not offenders_req, (
        "Write routes must include a 'request' parameter: " + ", ".join(offenders_req)
    )
    assert not offenders_parse_before_guard, (
        "Body parsing helpers must not be used before the guard is mounted (dependencies=Depends(precondition_guard)): "
        + ", ".join(offenders_parse_before_guard)
    )


# 7.1.38 — 415 Content-Type is enforced pre-body on write routes
def test_7_1_38_content_type_enforced_pre_body_on_write_routes() -> None:
    """Verifies 7.1.38 — Guard enforces 415 before parsing; wrappers have no PRE_*; ordering check via AST line numbers."""
    # Verifies section 7.1.38
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "Guard module app/guards/precondition.py must exist."
    t = _parse_ast(guard_mod)

    # Locate precondition_guard function
    fns = [fn for fn in _function_defs(t) if fn.name == "precondition_guard"]
    assert fns, "precondition_guard function must be defined."
    fn = fns[0]

    # Find first 415 literal and first presence/parse helper calls by line number
    first_415: Optional[int] = None
    first_presence_call: Optional[int] = None
    first_parse_call: Optional[int] = None
    for node in ast.walk(fn):
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and node.value == 415:
            ln = getattr(node, "lineno", None)
            if isinstance(ln, int):
                first_415 = ln if first_415 is None else min(first_415, ln)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_check_if_match_presence":
            first_presence_call = getattr(node, "lineno", first_presence_call)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_parse_if_match":
            first_parse_call = getattr(node, "lineno", first_parse_call)
    assert first_415 is not None, "precondition_guard must reference status 415 for Content-Type enforcement."
    if first_presence_call is not None:
        assert first_415 <= first_presence_call, (
            "Content-Type 415 enforcement must occur before If-Match presence checks."
        )
    if first_parse_call is not None:
        assert first_415 <= first_parse_call, (
            "Content-Type 415 enforcement must occur before If-Match parsing/normalisation."
        )

    # Wrappers under app/http must not contain PRE_* branches
    http_dir = APP_DIR / "http"
    if http_dir.exists():
        for py in _iter_py_files(http_dir):
            tt = _parse_ast(py)
            for n in ast.walk(tt):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("PRE_"):
                    pytest.fail(f"app/http wrappers must not reference PRE_* constants: {py} (found '{n.value}')")


# 7.1.39 — PRE_* lives only in the guard
def test_7_1_39_pre_only_in_guard() -> None:
    """Verifies 7.1.39 — No PRE_* outside guard; no If-Match parsing/comparison outside guard; no RUN_* in guard failures."""
    # Verifies section 7.1.39
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "Guard module app/guards/precondition.py must exist."

    offenders: list[str] = []
    for root in [APP_DIR / "routes", APP_DIR / "http"]:
        if not root.exists():
            continue
        for py in _iter_py_files(root):
            if py == guard_mod:
                continue
            t = _parse_ast(py)
            for n in ast.walk(t):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("PRE_"):
                    offenders.append(f"{py}: PRE constant '{n.value}' present")
                if isinstance(n, ast.Name) and n.id in {"normalize_if_match", "normalise_if_match", "compare_etag"}:
                    offenders.append(f"{py}: direct call/reference to {n.id}")
                if isinstance(n, ast.Attribute) and n.attr in {"normalize_if_match", "normalise_if_match", "compare_etag"}:
                    offenders.append(f"{py}: attribute reference to {n.attr}")
    assert not offenders, (
        "PRE_* and If-Match parsing/comparison must live only in the guard: " + ", ".join(map(str, offenders))
    )

    # Parse guard module and assert it imports PRECONDITION_ERROR_MAP
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "app/guards/precondition.py must exist."
    gt = _parse_ast(guard_mod)
    run_tokens: list[str] = []
    for n in ast.walk(gt):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("RUN_"):
            run_tokens.append(n.value)
    assert not run_tokens, "Guard failure branches must not contain RUN_* tokens."


# 7.1.40 — Canonical status mapping is declared and used
def test_7_1_40_canonical_status_mapping_declared_and_used() -> None:
    """Verifies 7.1.40 — Mapping contains required keys/statuses/codes; guard imports and uses it; no RUN_* in failures."""
    # Verifies section 7.1.40
    mapping_mod = APP_DIR / "config" / "error_mapping.py"
    assert mapping_mod.exists(), "app/config/error_mapping.py must exist."
    mt = _parse_ast(mapping_mod)

    # Extract PRECONDITION_ERROR_MAP dict literal
    mapping_dict: Optional[ast.Dict] = None
    if isinstance(mt, ast.Module):
        for n in mt.body:
            if isinstance(n, ast.Assign):
                for tgt in n.targets:
                    if isinstance(tgt, ast.Name) and tgt.id == "PRECONDITION_ERROR_MAP" and isinstance(n.value, ast.Dict):
                        mapping_dict = n.value
    assert isinstance(mapping_dict, ast.Dict), "PRECONDITION_ERROR_MAP must be defined as a dict literal."

    def _literal_str(node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    def _literal_int(node: ast.AST) -> Optional[int]:
        if isinstance(node, ast.Constant) and isinstance(node.value, int):
            return node.value
        return None

    vals: dict[str, dict[str, Any]] = {}
    for k, v in zip(mapping_dict.keys, mapping_dict.values):  # type: ignore[arg-type]
        key = _literal_str(k) or ""
        if not key or not isinstance(v, ast.Dict):
            continue
        entry: dict[str, Any] = {}
        for kk, vv in zip(v.keys, v.values):  # type: ignore[arg-type]
            k2 = _literal_str(kk) or ""
            if k2 == "code":
                entry["code"] = _literal_str(vv)
            if k2 == "status":
                entry["status"] = _literal_int(vv)
        vals[key] = entry

    exp = {
        "missing": ("PRE_IF_MATCH_MISSING", 428),
        "invalid_format": ("PRE_IF_MATCH_INVALID_FORMAT", 409),
        "mismatch_answers": ("PRE_IF_MATCH_ETAG_MISMATCH", 409),
        "mismatch_documents": ("PRE_IF_MATCH_ETAG_MISMATCH", 412),
    }
    missing: list[str] = []
    wrong: list[str] = []
    for k, (ecode, estatus) in exp.items():
        if k not in vals:
            missing.append(k)
            continue
        if vals[k].get("code") != ecode or vals[k].get("status") != estatus:
            wrong.append(f"{k} -> {vals[k]}")
    assert not missing and not wrong, (
        "PRECONDITION_ERROR_MAP must include required entries with correct codes/statuses. "
        + (f"Missing: {', '.join(missing)}. " if missing else "")
        + (f"Wrong: {', '.join(wrong)}" if wrong else "")
    )

    # Guard must import the mapping
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "app/guards/precondition.py must exist."
    gt = _parse_ast(guard_mod)
    imported = False
    for n in ast.walk(gt):
        if isinstance(n, ast.ImportFrom) and (n.module or "") == "app.config.error_mapping":
            for alias in n.names:
                if alias.name == "PRECONDITION_ERROR_MAP":
                    imported = True
    assert imported, "Guard must import PRECONDITION_ERROR_MAP via ImportFrom."

    run_tokens: list[str] = []
    for n in ast.walk(gt):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("RUN_"):
            run_tokens.append(n.value)
    assert not run_tokens, "Guard must not reference RUN_* tokens in failure branches."


# 7.1.41 — Reorder diagnostics emitted only by header emitter
def test_7_1_41_reorder_diagnostics_emitted_only_by_emitter() -> None:
    """Verifies 7.1.41 — Reorder diagnostics must be imported/called via emitter; no direct sets; emitter exposes both."""
    # Verifies section 7.1.41
    docs_routes = APP_DIR / "routes" / "documents.py"
    assert docs_routes.exists(), "app/routes/documents.py must exist."

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

    direct_sets = _scan_for_header_sets(docs_routes)
    direct_offenders = [f"line {ln}: {hdr}" for ln, hdr in direct_sets if hdr in {"X-List-ETag", "X-If-Match-Normalized"}]
    assert not direct_offenders, (
        "documents.py must not set diagnostic headers directly; use the emitter: " + ", ".join(direct_offenders)
    )

    emitter_mod = APP_DIR / "logic" / "header_emitter.py"
    assert emitter_mod.exists(), "app/logic/header_emitter.py must exist."
    emitter_src = emitter_mod.read_text(encoding="utf-8")
    for required in ("X-List-ETag", "X-If-Match-Normalized"):
        assert required in emitter_src, f"header_emitter must reference diagnostic header '{required}'."


# 7.1.42 — If-Match presence helper trims and treats blanks as missing
def test_7_1_42_if_match_presence_helper_trims_and_treats_blanks_as_missing() -> None:
    """Verifies 7.1.42 — Presence helper uses .strip and maps blanks to 'missing'; invoked before parse helpers."""
    # Verifies section 7.1.42
    guard_mod = APP_DIR / "guards" / "precondition.py"
    assert guard_mod.exists(), "app/guards/precondition.py must exist."
    t = _parse_ast(guard_mod)

    helpers = [fn for fn in _function_defs(t) if fn.name == "_check_if_match_presence"]
    assert helpers, "Guard must define presence helper '_check_if_match_presence'."
    helper = helpers[0]

    saw_strip = False
    saw_missing_code = False
    for n in ast.walk(helper):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "strip":
            saw_strip = True
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value == "PRE_IF_MATCH_MISSING":
            saw_missing_code = True
    assert saw_strip, "Presence helper must trim the If-Match value using .strip()."
    assert saw_missing_code, "Presence helper must map blanks to PRE_IF_MATCH_MISSING via mapping."

    guards = [fn for fn in _function_defs(t) if fn.name == "precondition_guard"]
    assert guards, "precondition_guard function must be defined."
    guard_fn = guards[0]
    presence_ln: Optional[int] = None
    parse_ln: Optional[int] = None
    for node in ast.walk(guard_fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == "_check_if_match_presence":
                presence_ln = getattr(node, "lineno", presence_ln)
            if node.func.id == "_parse_if_match":
                parse_ln = getattr(node, "lineno", parse_ln)
    assert presence_ln is not None, "precondition_guard must invoke _check_if_match_presence."
    if parse_ln is not None:
        assert presence_ln <= parse_ln, "Presence check must occur before If-Match parsing/normalisation."
