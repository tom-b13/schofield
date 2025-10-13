"""Architectural tests for Epic E – Response ingestion (Section 7.1).

All tests are static/AST-based to avoid runtime side effects. Each test
corresponds to a single subsection (7.1.x) and verifies only the assertions
specified in that subsection. Tests are intentionally failing until the
application code is implemented (strict TDD).
"""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, List, Optional, Tuple

import pytest


# -----
# Helpers: File discovery and safe AST parsing
# -----

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = PROJECT_ROOT / "app"
ROUTES_DIR = APP_DIR / "routes"
LOGIC_DIR = APP_DIR / "logic"
MODELS_DIR = APP_DIR / "models"


def py_files_under(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            # Skip __pycache__ or compiled artifacts directories if any leaked in
            if "__pycache__" in p.parts:
                continue
            files.append(p)
    return files


@dataclass
class ParsedModule:
    path: Path
    tree: ast.AST


def parse_module_safe(path: Path) -> Optional[ParsedModule]:
    try:
        code = path.read_text(encoding="utf-8")
    except Exception as e:  # pragma: no cover - filesystem error should fail test later
        return None
    try:
        tree = ast.parse(code, filename=str(path))
        return ParsedModule(path=path, tree=tree)
    except SyntaxError:
        # Failures are handled by callers by checking for None; tests will assert
        return None


def parse_many(files: Iterable[Path]) -> list[ParsedModule]:
    result: list[ParsedModule] = []
    for f in files:
        pm = parse_module_safe(f)
        if pm is not None:
            result.append(pm)
    return result


# -----
# Helpers: Route decorator inspection
# -----

HTTP_METHOD_DECORATORS = {"get", "post", "patch", "delete", "put"}


@dataclass
class RouteDef:
    method: str
    path: str
    func_name: str
    module_path: Path
    lineno: int


def find_routes_in_module(pm: ParsedModule) -> list[RouteDef]:
    routes: list[RouteDef] = []
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.FunctionDef):
            for dec in node.decorator_list:
                # Match patterns like @router.post("/path", ...)
                if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                    if dec.func.attr in HTTP_METHOD_DECORATORS and isinstance(dec.func.value, ast.Name):
                        # Require the attribute base name to look like an APIRouter instance name
                        if dec.func.value.id not in {"router", "api_router", "app"}:
                            continue
                        # Extract first positional argument as route path string
                        if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                            method = dec.func.attr
                            path = dec.args[0].value
                            routes.append(
                                RouteDef(method=method, path=path, func_name=node.name, module_path=pm.path, lineno=node.lineno)
                            )
    return routes


def all_routes() -> list[RouteDef]:
    route_files = py_files_under(ROUTES_DIR)
    parsed = parse_many(route_files)
    routes: list[RouteDef] = []
    for pm in parsed:
        routes.extend(find_routes_in_module(pm))
    return routes


def has_api_prefix_in_main(prefix: str = "/api/v1") -> bool:
    main_path = APP_DIR / "main.py"
    pm = parse_module_safe(main_path)
    if not pm:
        return False
    ok = False
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "include_router":
                # look for keyword arg prefix="/api/v1"
                for kw in node.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant) and kw.value.value == prefix:
                        ok = True
    return ok


# -----
# Helpers: Import and call-site detection
# -----

def module_imports_symbol(pm: ParsedModule, module_name: str, symbol: Optional[str] = None) -> bool:
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == module_name:
                if symbol is None:
                    return True
                for alias in node.names:
                    if alias.name == symbol:
                        return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module_name:
                    return True
    return False


def module_calls_symbol(pm: ParsedModule, name_predicate: Callable[[str], bool]) -> bool:
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.Call):
            # match direct name call or attribute call
            if isinstance(node.func, ast.Name) and name_predicate(node.func.id):
                return True
            if isinstance(node.func, ast.Attribute):
                # attribute: X.y, check attr and value name
                attr_name = node.func.attr
                if name_predicate(attr_name):
                    return True
                if isinstance(node.func.value, ast.Name) and name_predicate(node.func.value.id):
                    return True
    return False


def module_uses_http_client(pm: ParsedModule) -> bool:
    http_client_modules = {"requests", "httpx", "urllib.request", "aiohttp"}
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in {m.split(".")[0] for m in http_client_modules}:
                    return True
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.split(".")[0] in {m.split(".")[0] for m in http_client_modules}:
                return True
    return False


def module_contains_sql_strings(pm: ParsedModule) -> bool:
    """Detect inline SQL by scanning runtime string literals via AST.

    This intentionally ignores comments and docstrings to prevent false
    positives from English prose. Only actual string literals reachable at
    runtime are considered. A match requires one of the following tokens to
    appear within a single literal:
    - "INSERT INTO "
    - "DELETE FROM "
    - "SELECT "
    - both "UPDATE " and " SET " within the same literal
    """
    tree = pm.tree

    # Collect docstring Constant nodes (module/class/function first statement)
    docstring_ids: set[int] = set()
    for container in ast.walk(tree):
        if isinstance(container, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            body = getattr(container, "body", [])
            if body:
                first = body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                    docstring_ids.add(id(first.value))

    # Now scan all string Constant nodes that are not docstrings
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docstring_ids:
                continue  # skip docstrings
            s = node.value.upper()
            if "INSERT INTO " in s:
                return True
            if "DELETE FROM " in s:
                return True
            if "SELECT " in s:
                return True
            if "UPDATE " in s and " SET " in s:
                return True
    return False


def find_class_defs(pm: ParsedModule) -> list[ast.ClassDef]:
    return [n for n in ast.walk(pm.tree) if isinstance(n, ast.ClassDef)]


def class_has_field_annotation(cls: ast.ClassDef, field_name: str) -> bool:
    for node in cls.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == field_name:
                return True
    return False


def class_is_enum_with_literals(cls: ast.ClassDef, literals: set[str]) -> bool:
    # Very lightweight: check assignments of uppercase names to string constants
    values: set[str] = set()
    for node in cls.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    values.add(node.value.value)
    return values == literals and bool(values)


def find_unique_constraint_in_sqla(pm: ParsedModule, table_or_class: str, columns: tuple[str, str]) -> bool:
    # Heuristic: look for UniqueConstraint("col1", "col2") or __table_args__ including UniqueConstraint
    col1, col2 = columns
    src = pm.path.read_text(encoding="utf-8")
    return (
        f"UniqueConstraint(\"{col1}\", \"{col2}\")" in src
        or f"UniqueConstraint('{col1}', '{col2}')" in src
        or ("__table_args__" in src and col1 in src and col2 in src and "UniqueConstraint" in src)
    )


def class_has_integer_column(pm: ParsedModule, cls: ast.ClassDef, field_name: str) -> bool:
    # Heuristic: search for Column(Integer) patterns within class body
    for node in cls.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == field_name for t in node.targets):
                if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "Column":
                    # check first arg type name contains Integer
                    if node.value.args:
                        arg0 = node.value.args[0]
                        if isinstance(arg0, ast.Name) and arg0.id.lower().startswith("integer"):
                            return True
                        if isinstance(arg0, ast.Attribute) and arg0.attr.lower().startswith("integer"):
                            return True
    return False


# -----
# 7.1.1 — 7.1.6: Routes existence under /api/v1
# -----


def _assert_route_exists(method: str, subpath: str) -> Tuple[Optional[RouteDef], list[RouteDef]]:
    routes = all_routes()
    matches = [r for r in routes if r.method.lower() == method.lower() and r.path == subpath]
    return (matches[0] if len(matches) == 1 else None, routes)


def _require_api_prefix() -> None:
    assert has_api_prefix_in_main("/api/v1"), "FastAPI app must include api_router with prefix '/api/v1'"


def _missing_route_fail(method: str, path: str, routes: list[RouteDef]) -> None:
    pretty = "\n".join(f"- {r.method.upper()} {r.path} in {r.module_path}:{r.lineno}" for r in routes) or "<no routes found>"
    pytest.fail(
        f"Expected route {method.upper()} {path} not found or not unique.\nDiscovered routes:\n{pretty}"
    )


def _find_handler_module_for(method: str, subpath: str) -> Optional[ParsedModule]:
    rd, _ = _assert_route_exists(method, subpath)
    if not rd:
        return None
    return parse_module_safe(rd.module_path)


def _assert_handler_has_if_match(pm: ParsedModule) -> bool:
    # Check for a function with a parameter declared as Header(..., alias="If-Match", ...)
    # Requiredness is enforced by Ellipsis ("...") as the default.
    def is_ellipsis(node: ast.AST) -> bool:
        # Python 3.11 represents ... as ast.Constant(Ellipsis)
        return (isinstance(node, ast.Constant) and node.value is Ellipsis) or isinstance(node, ast.Ellipsis)

    for node in ast.walk(pm.tree):
        if isinstance(node, ast.FunctionDef):
            for inner in ast.walk(node):
                if isinstance(inner, ast.Call):
                    func = inner.func
                    if (isinstance(func, ast.Name) and func.id == "Header") or (
                        isinstance(func, ast.Attribute) and func.attr == "Header"
                    ):
                        alias_ok = False
                        required_ok = False
                        # Check alias keyword
                        for kw in inner.keywords:
                            if kw.arg == "alias" and isinstance(kw.value, ast.Constant) and kw.value.value == "If-Match":
                                alias_ok = True
                        # Check Ellipsis provided as default via positional or keyword
                        if inner.args:
                            if any(is_ellipsis(arg) for arg in inner.args):
                                required_ok = True
                        for kw in inner.keywords:
                            if kw.arg in {"default", None} and is_ellipsis(kw.value):
                                required_ok = True
                        if alias_ok and required_ok:
                            return True
    return False


# 7.1.1
def test_post_response_sets_route_exists() -> None:
    """7.1.1 — POST /response-sets route exists under /api/v1."""
    # Verify API prefix is configured
    _require_api_prefix()

    # Assert route exists exactly once
    rd, routes = _assert_route_exists("post", "/response-sets")
    if not rd:
        _missing_route_fail("post", "/api/v1/response-sets", routes)


# 7.1.2
def test_get_screen_route_exists() -> None:
    """7.1.2 — GET /response-sets/{response_set_id}/screens/{screen_key} route exists."""
    _require_api_prefix()
    subpath = "/response-sets/{response_set_id}/screens/{screen_key}"
    rd, routes = _assert_route_exists("get", subpath)
    if not rd:
        _missing_route_fail("get", f"/api/v1{subpath}", routes)


# 7.1.3
def test_patch_single_answer_route_exists() -> None:
    """7.1.3 — PATCH /response-sets/{response_set_id}/answers/{question_id} route exists."""
    _require_api_prefix()
    subpath = "/response-sets/{response_set_id}/answers/{question_id}"
    rd, routes = _assert_route_exists("patch", subpath)
    if not rd:
        _missing_route_fail("patch", f"/api/v1{subpath}", routes)


# 7.1.4
def test_delete_single_answer_route_exists() -> None:
    """7.1.4 — DELETE /response-sets/{response_set_id}/answers/{question_id} route exists."""
    _require_api_prefix()
    subpath = "/response-sets/{response_set_id}/answers/{question_id}"
    rd, routes = _assert_route_exists("delete", subpath)
    if not rd:
        _missing_route_fail("delete", f"/api/v1{subpath}", routes)


# 7.1.5
def test_post_batch_answers_route_exists() -> None:
    """7.1.5 — POST /response-sets/{response_set_id}/answers:batch route exists."""
    _require_api_prefix()
    subpath = "/response-sets/{response_set_id}/answers:batch"
    rd, routes = _assert_route_exists("post", subpath)
    if not rd:
        _missing_route_fail("post", f"/api/v1{subpath}", routes)


# 7.1.6
def test_delete_response_set_route_exists() -> None:
    """7.1.6 — DELETE /response-sets/{response_set_id} route exists."""
    _require_api_prefix()
    subpath = "/response-sets/{response_set_id}"
    rd, routes = _assert_route_exists("delete", subpath)
    if not rd:
        _missing_route_fail("delete", f"/api/v1{subpath}", routes)


# 7.1.7
def test_reuses_single_screen_view_assembly_component() -> None:
    """7.1.7 — Reusable screen_view assembly component is shared across GET and post-save."""
    # Locate GET and PATCH handler modules
    get_pm = _find_handler_module_for("get", "/response-sets/{response_set_id}/screens/{screen_key}")
    patch_pm = _find_handler_module_for("patch", "/response-sets/{response_set_id}/answers/{question_id}")
    if not get_pm or not patch_pm:
        pytest.fail("Expected GET screen and PATCH save handlers not found for screen assembly reuse check")

    # Identify the assembly callable name used by GET (assemble/build + screen + view)
    def is_assembly_name(n: str) -> bool:
        nL = n.lower()
        return ("assemble" in nL or "build" in nL) and ("screen" in nL and "view" in nL)

    get_assembly_name: Optional[str] = None
    for node in ast.walk(get_pm.tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
            if name and is_assembly_name(name):
                get_assembly_name = name
                break
    assert get_assembly_name, "GET screen handler must call a screen_view assembly function"

    # Assert PATCH calls the same-named callable
    assert module_calls_symbol(patch_pm, lambda n: n == get_assembly_name), (
        "PATCH save handler must call the same screen_view assembly callable name as GET"
    )

    # Both handlers must import the callable from the same module (ImportFrom.module equality)
    def imported_from_module(pm: ParsedModule, symbol: str) -> Optional[str]:
        for n in ast.walk(pm.tree):
            if isinstance(n, ast.ImportFrom):
                for a in n.names:
                    if a.name == symbol:
                        return n.module or ""
        return None

    get_from = imported_from_module(get_pm, get_assembly_name) or ""
    patch_from = imported_from_module(patch_pm, get_assembly_name) or ""
    assert get_from and patch_from and (get_from == patch_from), (
        "GET and PATCH must import the assembly callable from the same module"
    )

    # Exactly one FunctionDef with that name across APP_DIR, and not defined in route modules
    defs: list[tuple[Path, ast.FunctionDef]] = []
    for pm in parse_many(py_files_under(APP_DIR)):
        for n in ast.walk(pm.tree):
            if isinstance(n, ast.FunctionDef) and n.name == get_assembly_name:
                defs.append((pm.path, n))
    assert (
        len(defs) == 1
    ), f"Assembly callable must be defined exactly once; found definitions: {[str(p) for p, _ in defs]}"
    assert not str(defs[0][0]).startswith(str(ROUTES_DIR)), "Assembly callable must not be defined in route modules"


# 7.1.8
def test_visibility_helpers_used_in_process_no_http() -> None:
    """7.1.8 — Visibility helpers are imported/called in-process; no HTTP clients used."""
    get_pm = _find_handler_module_for("get", "/response-sets/{response_set_id}/screens/{screen_key}")
    patch_pm = _find_handler_module_for("patch", "/response-sets/{response_set_id}/answers/{question_id}")
    if not get_pm or not patch_pm:
        pytest.fail("Expected GET screen and PATCH save handlers not found for visibility helpers check")

    # Required helpers
    assert module_imports_symbol(get_pm, "app.logic.visibility_rules"), "GET handler must import visibility_rules"
    assert module_imports_symbol(patch_pm, "app.logic.visibility_rules"), "PATCH handler must import visibility_rules"
    assert module_imports_symbol(get_pm, "app.logic.visibility_delta"), "GET handler must import visibility_delta"
    assert module_imports_symbol(patch_pm, "app.logic.visibility_delta"), "PATCH handler must import visibility_delta"
    assert module_imports_symbol(get_pm, "app.logic.repository_screens"), "GET handler must import repository_screens"
    assert module_imports_symbol(patch_pm, "app.logic.repository_screens"), "PATCH handler must import repository_screens"

    # No HTTP client modules imported in these handlers
    assert not module_uses_http_client(get_pm), "GET handler must not import HTTP clients for visibility"
    assert not module_uses_http_client(patch_pm), "PATCH handler must not import HTTP clients for visibility"


# 7.1.9
def test_answer_hydration_uses_repository_helpers_no_inline_sql() -> None:
    """7.1.9 — Hydration via repository_answers.get_existing_answer; no inline SQL in handlers."""
    get_pm = _find_handler_module_for("get", "/response-sets/{response_set_id}/screens/{screen_key}")
    patch_pm = _find_handler_module_for("patch", "/response-sets/{response_set_id}/answers/{question_id}")
    if not get_pm or not patch_pm:
        pytest.fail("Expected GET screen and PATCH save handlers not found for hydration checks")

    assert module_imports_symbol(get_pm, "app.logic.repository_answers"), "GET handler must import repository_answers"
    assert module_imports_symbol(patch_pm, "app.logic.repository_answers"), "PATCH handler must import repository_answers"
    assert module_calls_symbol(get_pm, lambda n: n == "get_existing_answer"), "GET handler must call get_existing_answer"
    assert module_calls_symbol(patch_pm, lambda n: n == "get_existing_answer"), "PATCH handler must call get_existing_answer"
    assert not module_contains_sql_strings(get_pm), "GET handler must not contain inline SQL strings for hydration"
    assert not module_contains_sql_strings(patch_pm), "PATCH handler must not contain inline SQL strings for hydration"


# 7.1.10
def test_screen_definition_retrieval_uses_repository_helpers() -> None:
    """7.1.10 — Screen definition retrieval via repository_screens.list_questions_for_screen; no inline SQL."""
    get_pm = _find_handler_module_for("get", "/response-sets/{response_set_id}/screens/{screen_key}")
    patch_pm = _find_handler_module_for("patch", "/response-sets/{response_set_id}/answers/{question_id}")
    if not get_pm or not patch_pm:
        pytest.fail("Expected GET screen and PATCH save handlers not found for screen definition checks")

    assert module_imports_symbol(get_pm, "app.logic.repository_screens"), "GET handler must import repository_screens"
    assert module_imports_symbol(patch_pm, "app.logic.repository_screens"), "PATCH handler must import repository_screens"
    assert module_calls_symbol(get_pm, lambda n: n == "list_questions_for_screen"), "GET handler must call list_questions_for_screen"
    assert module_calls_symbol(patch_pm, lambda n: n == "list_questions_for_screen"), "PATCH handler must call list_questions_for_screen"
    assert not module_contains_sql_strings(get_pm), "GET handler must not contain inline SQL for screen definitions"
    assert not module_contains_sql_strings(patch_pm), "PATCH handler must not contain inline SQL for screen definitions"


# 7.1.11
def test_db_uniqueness_on_response_set_id_and_question_id() -> None:
    """7.1.11 — Unique constraint exists on (response_set_id, question_id) in Response model."""
    model_files = py_files_under(MODELS_DIR)
    parsed = parse_many(model_files)
    if not parsed:
        pytest.fail("No models found; expected Response model with uniqueness constraint over (response_set_id, question_id)")
    found = any(
        find_unique_constraint_in_sqla(pm, "Response", ("response_set_id", "question_id")) for pm in parsed
    )
    assert found, "Expected a UniqueConstraint over (response_set_id, question_id) on the Response persistence model"


# 7.1.12
def test_response_state_version_column_exists_and_is_integer() -> None:
    """7.1.12 — Response.state_version column exists and is integer-typed in ORM mapping."""
    model_files = py_files_under(MODELS_DIR)
    parsed = parse_many(model_files)
    if not parsed:
        pytest.fail("No models found; expected Response model with integer state_version column")
    found = False
    for pm in parsed:
        for cls in find_class_defs(pm):
            if cls.name.lower() == "response":
                if class_has_integer_column(pm, cls, "state_version"):
                    found = True
    assert found, "Expected Response model to declare an integer Column named state_version"


# 7.1.13
def test_screen_etag_computed_via_dedicated_component() -> None:
    """7.1.13 — compute_screen_etag exists and is used by GET and post-save handlers."""
    # Section 7.1.13
    # - Assert compute_screen_etag is defined in app/logic/etag.py
    # - Assert GET and PATCH import and call compute_screen_etag

    get_pm = _find_handler_module_for("get", "/response-sets/{response_set_id}/screens/{screen_key}")
    patch_pm = _find_handler_module_for("patch", "/response-sets/{response_set_id}/answers/{question_id}")
    if not get_pm or not patch_pm:
        pytest.fail("Expected GET screen and PATCH save handlers not found for Screen-ETag checks")

    # Verify the callable is actually defined as a FunctionDef in app/logic/etag.py
    etag_module = LOGIC_DIR / "etag.py"
    assert etag_module.exists(), "Expected app/logic/etag.py module with compute_screen_etag()"
    etag_pm = parse_module_safe(etag_module)
    assert etag_pm is not None, "Failed to parse app/logic/etag.py"
    has_fn_def = any(isinstance(n, ast.FunctionDef) and n.name == "compute_screen_etag" for n in ast.walk(etag_pm.tree))
    assert has_fn_def, "compute_screen_etag must be defined as a function in app/logic/etag.py"

    # Both handlers import and call it
    assert module_imports_symbol(get_pm, "app.logic.etag"), "GET handler must import app.logic.etag"
    assert module_imports_symbol(patch_pm, "app.logic.etag"), "PATCH handler must import app.logic.etag"
    assert module_calls_symbol(get_pm, lambda n: n == "compute_screen_etag"), "GET handler must call compute_screen_etag"
    assert module_calls_symbol(patch_pm, lambda n: n == "compute_screen_etag"), "PATCH handler must call compute_screen_etag"


# 7.1.14
def test_if_match_declared_as_required_on_write_routes() -> None:
    """7.1.14 — Write routes declare a required If-Match header parameter."""
    # PATCH answer
    patch_pm = _find_handler_module_for("patch", "/response-sets/{response_set_id}/answers/{question_id}")
    # DELETE answer
    delete_answer_pm = _find_handler_module_for("delete", "/response-sets/{response_set_id}/answers/{question_id}")
    # DELETE response set
    delete_set_pm = _find_handler_module_for("delete", "/response-sets/{response_set_id}")
    if not (patch_pm and delete_answer_pm and delete_set_pm):
        pytest.fail("Expected write handler modules not found for If-Match header requirement check")
    assert _assert_handler_has_if_match(patch_pm), "PATCH save must declare required If-Match Header(...) with Ellipsis"
    assert _assert_handler_has_if_match(delete_answer_pm), "DELETE answer must declare required If-Match Header(...) with Ellipsis"
    assert _assert_handler_has_if_match(delete_set_pm), "DELETE response-set must declare required If-Match Header(...) with Ellipsis"


# 7.1.15
def test_no_idempotency_store_referenced_by_write_paths() -> None:
    """7.1.15 — Write handlers do not reference any idempotency storage or keys."""
    targets = [
        _find_handler_module_for("patch", "/response-sets/{response_set_id}/answers/{question_id}"),
        _find_handler_module_for("post", "/response-sets/{response_set_id}/answers:batch"),
        _find_handler_module_for("delete", "/response-sets/{response_set_id}/answers/{question_id}"),
        _find_handler_module_for("delete", "/response-sets/{response_set_id}"),
    ]
    if not all(targets):
        pytest.fail("Expected write handler modules not found for idempotency reference check")
    for pm in targets:  # type: ignore[assignment]
        src = pm.path.read_text(encoding="utf-8")
        assert (
            "idempotency" not in src.lower()
        ), f"Idempotency references must not appear in write handler: {pm.path}"


# 7.1.16
def test_enum_resolution_via_dedicated_callable_and_used_by_save_and_batch() -> None:
    """7.1.16 — A single callable resolves enum options; both save and batch use it."""
    save_pm = _find_handler_module_for("patch", "/response-sets/{response_set_id}/answers/{question_id}")
    batch_pm = _find_handler_module_for("post", "/response-sets/{response_set_id}/answers:batch")
    if not (save_pm and batch_pm):
        pytest.fail("Expected save and batch handler modules not found for enum resolution delegation checks")

    # Search logic for a single resolver function
    logic_files = py_files_under(LOGIC_DIR)
    parsed_logic = parse_many(logic_files)

    resolver_names: set[str] = set()
    for pm in parsed_logic:
        for node in ast.walk(pm.tree):
            if isinstance(node, ast.FunctionDef) and (
                node.name.lower().startswith("resolve_")
                and ("enum" in node.name.lower() or "option" in node.name.lower())
            ):
                resolver_names.add(node.name)
    assert resolver_names, "Expected a dedicated resolver callable for enum option resolution in app/logic"
    assert (
        len(resolver_names) == 1
    ), f"Expected exactly one resolver callable, found: {sorted(resolver_names)}"
    resolver = list(resolver_names)[0]
    assert module_calls_symbol(save_pm, lambda n: n == resolver), "Save handler must call the enum resolver"
    assert module_calls_symbol(batch_pm, lambda n: n == resolver), "Batch handler must call the enum resolver"


# 7.1.17
def test_text_answers_not_trimmed_in_models_or_serialisers() -> None:
    """7.1.17 — Text answers must pass through unchanged; no trim/strip in write paths."""
    save_pm = _find_handler_module_for("patch", "/response-sets/{response_set_id}/answers/{question_id}")
    batch_pm = _find_handler_module_for("post", "/response-sets/{response_set_id}/answers:batch")
    if not (save_pm and batch_pm):
        pytest.fail("Expected save and batch handler modules not found for text normalisation checks")
    # Scope route-module scan strictly to the write-path handlers' function bodies
    def _assert_no_trim_in_function(pm: ParsedModule, func_name: str) -> None:
        code = pm.path.read_text(encoding="utf-8")
        tree = pm.tree
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                start = getattr(node, "lineno", None)
                end = getattr(node, "end_lineno", None)
                if start is None or end is None:
                    continue
                # Slice the exact body region for the function
                lines = code.splitlines()
                segment = "\n".join(lines[start - 1 : end]).lower()
                assert ".strip(" not in segment and ".trim(" not in segment, (
                    f"Write-path handler must not trim text answers: {pm.path}::{func_name}"
                )
                return
        pytest.fail(f"Expected to find handler function '{func_name}' in module {pm.path}")

    _assert_no_trim_in_function(save_pm, "autosave_answer")
    _assert_no_trim_in_function(batch_pm, "batch_upsert_answers")

    # Limit logic-layer scan strictly to the canonicalisation module
    canonical_path = LOGIC_DIR / "answer_canonical.py"
    if canonical_path.exists():
        src = canonical_path.read_text(encoding="utf-8").lower()
        assert ".strip(" not in src and ".trim(" not in src, (
            f"Text normalisation (strip/trim) must not appear in logic write path: {canonical_path}"
        )


# 7.1.18
def test_number_boolean_canonicalisation_resides_in_validation_layer_and_used_by_handlers() -> None:
    """7.1.18 — Numeric finiteness/boolean checks implemented in a validation/canonicalisation module and used by handlers."""
    save_pm = _find_handler_module_for("patch", "/response-sets/{response_set_id}/answers/{question_id}")
    batch_pm = _find_handler_module_for("post", "/response-sets/{response_set_id}/answers:batch")
    if not (save_pm and batch_pm):
        pytest.fail("Expected save and batch handler modules not found for validation canonicalisation checks")

    # Look for validation module and functions
    logic_files = py_files_under(LOGIC_DIR)
    parsed_logic = parse_many(logic_files)
    has_numeric = False
    has_boolean = False
    for pm in parsed_logic:
        src = pm.path.read_text(encoding="utf-8").lower()
        if "isfinite" in src or "math.isfinite" in src or "is_finite" in src:
            has_numeric = True
        if "coerce_bool" in src or "canonical" in src and "bool" in src or "to_boolean" in src:
            has_boolean = True
    assert has_numeric and has_boolean, "Expected dedicated validation/canonicalisation functions for numeric/boolean types in logic modules"

    # Handlers must call into validation functions (heuristic by name fragments)
    assert module_calls_symbol(save_pm, lambda n: "finite" in n.lower() or "bool" in n.lower()), "Save handler must call validation functions"
    assert module_calls_symbol(batch_pm, lambda n: "finite" in n.lower() or "bool" in n.lower()), "Batch handler must call validation functions"


# 7.1.19
def test_domain_event_types_defined_once_as_constants_or_enums() -> None:
    """7.1.19 — 'response.saved' and 'response_set.deleted' defined centrally and referenced elsewhere."""
    app_files = py_files_under(APP_DIR)
    occurrences = 0
    defining_modules: set[Path] = set()
    for p in app_files:
        src = p.read_text(encoding="utf-8")
        if "response.saved" in src or "response_set.deleted" in src:
            occurrences += src.count("response.saved") + src.count("response_set.deleted")
            defining_modules.add(p)
    assert occurrences > 0, "Expected central definitions for domain event types not found"
    assert (
        len(defining_modules) == 1
    ), f"Domain event type string literals must be defined once; found in: {sorted(map(str, defining_modules))}"


# 7.1.20
def test_event_emission_confined_to_save_and_delete_flows() -> None:
    """7.1.20 — Only save and delete flows publish the specified domain events."""
    publisher_candidates = py_files_under(LOGIC_DIR)
    pub_found = False
    for p in publisher_candidates:
        if "publish" in p.read_text(encoding="utf-8").lower() and "event" in p.read_text(encoding="utf-8").lower():
            pub_found = True
            break
    assert pub_found, "Expected an event publisher in app/logic for domain events"

    # Handlers are the only allowed callers
    save_pm = _find_handler_module_for("patch", "/response-sets/{response_set_id}/answers/{question_id}")
    delete_pm = _find_handler_module_for("delete", "/response-sets/{response_set_id}")
    if not (save_pm and delete_pm):
        pytest.fail("Expected save and delete handler modules not found for event emission confinement checks")
    # Heuristic: ensure no other route modules call publish
    for pm in parse_many(py_files_under(ROUTES_DIR)):
        src = pm.path.read_text(encoding="utf-8").lower()
        if pm.path not in {save_pm.path, delete_pm.path}:  # compare by path, not ParsedModule identity
            assert "publish" not in src or "event" not in src, f"Unexpected event publishing in module: {pm.path}"

    # Positive assertions: save and delete handlers publish a domain event
    save_src = save_pm.path.read_text(encoding="utf-8").lower()
    delete_src = delete_pm.path.read_text(encoding="utf-8").lower()
    assert "publish" in save_src, "Save handler must invoke the event publisher for response.saved"
    assert "publish" in delete_src, "Delete handler must invoke the event publisher for response_set.deleted"


# 7.1.21
def test_output_schema_types_exist_for_response_bodies() -> None:
    """7.1.21 — Types exist for outputs: screen_view, saved, visibility_delta, batch_result, events."""
    logic_and_models = parse_many(py_files_under(APP_DIR))
    required = {
        "screen_view": {"class": {"ScreenView", "ScreenViewModel"}},
        "saved": {"class": {"Saved", "SavedResult"}},
        "visibility_delta": {"class": {"VisibilityDelta"}},
        "batch_result": {"class": {"BatchResult"}},
        "events": {"class": {"Events", "EventList"}},
    }

    found_map: dict[str, bool] = {k: False for k in required}
    for pm in logic_and_models:
        for cls in find_class_defs(pm):
            for key, spec in required.items():
                if any(cls.name == name for name in spec.get("class", set())):
                    found_map[key] = True

    missing = [k for k, v in found_map.items() if not v]
    assert not missing, f"Missing output schema types for: {missing}"

    # Additionally assert these types are referenced by route response models or serializer bindings
    route_modules = parse_many(py_files_under(ROUTES_DIR))

    def class_referenced_in_routes(class_names: set[str]) -> bool:
        for pm in route_modules:
            # Check explicit import-from usage: from X import ClassName
            for node in ast.walk(pm.tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        if alias.name in class_names:
                            return True
                # Check decorator/route call keyword: response_model=ClassName
                if isinstance(node, ast.Call):
                    for kw in node.keywords:
                        if kw.arg == "response_model":
                            val = kw.value
                            if isinstance(val, ast.Name) and val.id in class_names:
                                return True
                            if isinstance(val, ast.Attribute) and val.attr in class_names:
                                return True
        return False

    missing_refs: list[str] = []
    for key, spec in required.items():
        if not class_referenced_in_routes(spec.get("class", set())):
            missing_refs.append(key)
    assert not missing_refs, (
        "Output schema types must be referenced by route response models or serializers: "
        f"{missing_refs}"
    )


# 7.1.22
def test_single_reusable_type_for_now_visible_items() -> None:
    """7.1.22 — One serialisable type for visibility_delta.now_visible[] items with fields {question, answer}."""
    # Section 7.1.22
    # - Enforce single reusable class with fields {question, answer}
    # - Assert both GET and PATCH handlers import/reference this class

    parsed = parse_many(py_files_under(APP_DIR))
    candidates: list[Tuple[Path, ast.ClassDef]] = []
    for pm in parsed:
        for cls in find_class_defs(pm):
            if class_has_field_annotation(cls, "question") and class_has_field_annotation(cls, "answer"):
                candidates.append((pm.path, cls))
    assert candidates, "Expected a reusable NowVisible item type with fields {question, answer}"
    assert (
        len(candidates) == 1
    ), f"Expected exactly one NowVisible item type; found: {[f'{p}:{c.name}' for p, c in candidates]}"

    defining_path, defining_cls = candidates[0]

    # Compute module path for ImportFrom checks, e.g., app.models.foo
    try:
        rel = defining_path.relative_to(PROJECT_ROOT)
    except ValueError:
        rel = defining_path
    module_name = ".".join(rel.with_suffix("").parts)
    # Ensure module_name starts with 'app.'
    if not module_name.startswith("app."):
        module_name = f"app.{module_name.split('app.', 1)[-1]}" if "app." in module_name else f"app.{module_name}"

    get_pm = _find_handler_module_for("get", "/response-sets/{response_set_id}/screens/{screen_key}")
    patch_pm = _find_handler_module_for("patch", "/response-sets/{response_set_id}/answers/{question_id}")
    if not (get_pm and patch_pm):
        pytest.fail("Expected GET screen and PATCH save handlers not found for now_visible type reuse checks")

    assert module_imports_symbol(get_pm, module_name, defining_cls.name), (
        f"GET handler must import {defining_cls.name} from {module_name}"
    )
    assert module_imports_symbol(patch_pm, module_name, defining_cls.name), (
        f"PATCH handler must import {defining_cls.name} from {module_name}"
    )


# 7.1.23
def test_screen_etag_header_projected_wherever_screen_view_returned() -> None:
    """7.1.23 — Handlers returning screen_view also set Screen-ETag header from screen_view.etag."""
    get_pm = _find_handler_module_for("get", "/response-sets/{response_set_id}/screens/{screen_key}")
    patch_pm = _find_handler_module_for("patch", "/response-sets/{response_set_id}/answers/{question_id}")
    if not (get_pm and patch_pm):
        pytest.fail("Expected GET screen and PATCH save handlers not found for Screen-ETag header checks")

    def sets_screen_etag(pm: ParsedModule) -> bool:
        src = pm.path.read_text(encoding="utf-8")
        return ("Screen-ETag" in src) and ("screen_view.etag" in src)

    assert sets_screen_etag(get_pm), "GET screen handler must set Screen-ETag from screen_view.etag"
    assert sets_screen_etag(patch_pm), "PATCH save handler must set Screen-ETag from screen_view.etag"


# 7.1.24
def test_batch_result_envelope_defined_with_ordered_items() -> None:
    """7.1.24 — BatchResult type with items[] as list; handler constructs without sorting."""
    # Type exists with items annotation
    parsed = parse_many(py_files_under(APP_DIR))
    found_type = False
    for pm in parsed:
        for cls in find_class_defs(pm):
            if cls.name == "BatchResult" and class_has_field_annotation(cls, "items"):
                found_type = True
    assert found_type, "Expected BatchResult type with an 'items' field"

    # Batch handler uses incoming order — no sorting calls within the handler body
    batch_pm = _find_handler_module_for("post", "/response-sets/{response_set_id}/answers:batch")
    if not batch_pm:
        pytest.fail("Expected batch handler module not found for ordered items check")

    # Inspect only the body of FunctionDef(name='batch_upsert_answers') for sorted() calls
    def _assert_no_sorted_in_function(pm: ParsedModule, func_name: str) -> None:
        for node in ast.walk(pm.tree):
            if isinstance(node, ast.FunctionDef) and node.name == func_name:
                for inner in ast.walk(node):
                    if isinstance(inner, ast.Call):
                        fn = inner.func
                        if isinstance(fn, ast.Name) and fn.id == "sorted":
                            pytest.fail("Batch handler must not call sorted() when constructing items[]")
                        if isinstance(fn, ast.Attribute) and fn.attr == "sorted":
                            pytest.fail("Batch handler must not call sorted() when constructing items[]")
                return
        pytest.fail(f"Expected to find handler function '{func_name}' in module {pm.path}")

    _assert_no_sorted_in_function(batch_pm, "batch_upsert_answers")


# 7.1.25
def test_question_kind_enum_excludes_multi_value_kinds() -> None:
    """7.1.25 — Question kind enum contains exactly {short_string, long_text, number, boolean, enum_single}."""
    allowed = {"short_string", "long_text", "number", "boolean", "enum_single"}
    parsed = parse_many(py_files_under(APP_DIR))
    found_ok = False
    for pm in parsed:
        for cls in find_class_defs(pm):
            if cls.name.lower() in {"questionkind", "question_kind"} and class_is_enum_with_literals(cls, allowed):
                found_ok = True
    assert found_ok, "Expected a QuestionKind enum with exactly the allowed single-value kinds for Epic E"


# 7.1.26
def test_dedicated_filter_step_for_visible_questions_before_assembly() -> None:
    """7.1.26 — A named filter function subsets to visible questions before screen assembly."""
    get_pm = _find_handler_module_for("get", "/response-sets/{response_set_id}/screens/{screen_key}")
    if not get_pm:
        pytest.fail("Expected GET screen handler module not found for visible filter step check")

    # Find call line numbers for filter and assembly
    filter_line: Optional[int] = None
    assembly_line: Optional[int] = None
    for node in ast.walk(get_pm.tree):
        if isinstance(node, ast.Call):
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name:
                lname = name.lower()
                if "filter" in lname and "visible" in lname:
                    filter_line = getattr(node, "lineno", None)
                if ("assemble" in lname or "build" in lname) and ("screen" in lname and "view" in lname):
                    assembly_line = getattr(node, "lineno", None)
    assert filter_line is not None and assembly_line is not None, "Expected both a visible filter call and screen assembly call"
    assert (
        filter_line < assembly_line
    ), "Visible filter must be invoked before the screen_view assembly in the GET flow"


# 7.1.27
def test_post_save_reuses_same_screen_assembly_as_get() -> None:
    """7.1.27 — Post-save flow reuses the same screen assembly callable used by GET."""
    get_pm = _find_handler_module_for("get", "/response-sets/{response_set_id}/screens/{screen_key}")
    patch_pm = _find_handler_module_for("patch", "/response-sets/{response_set_id}/answers/{question_id}")
    if not (get_pm and patch_pm):
        pytest.fail("Expected GET and PATCH handler modules not found for screen assembly reuse check")

    # Identify assembly function name used by GET
    get_assembly: Optional[str] = None
    for node in ast.walk(get_pm.tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
            if name and ("assemble" in name.lower() or "build" in name.lower()) and ("screen" in name.lower() and "view" in name.lower()):
                get_assembly = name
                break
    assert get_assembly, "GET handler must call a screen_view assembly function"
    # PATCH must call the same function name
    assert module_calls_symbol(patch_pm, lambda n: n == get_assembly), (
        "PATCH save must call the same screen_view assembly function as GET"
    )
