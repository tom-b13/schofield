"""Architectural tests for EPIC G — Build questionnaire (Section 7.1).

Each test maps 1:1 to a 7.1.x subsection and asserts only the
requirements listed there. All checks use static filesystem/AST/JSON
inspection to avoid import-time side effects. Tests are expected to
fail until the corresponding implementation exists (strict TDD).
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional

import pytest


# Root and common directories
PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_DIR = PROJECT_ROOT / "app"
SCHEMAS_DIR = PROJECT_ROOT / "schemas"
DOCS_SCHEMAS_DIR = PROJECT_ROOT / "docs" / "schemas"
MIGRATIONS_DIR = PROJECT_ROOT / "migrations"
ROUTES_DIR = APP_DIR / "routes"
LOGIC_DIR = APP_DIR / "logic"
MODELS_DIR = APP_DIR / "models"
DB_DIR = APP_DIR / "db"


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - explicit failure in test
        pytest.fail(f"Failed to parse JSON at {path}: {exc}")


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:  # pragma: no cover - explicit failure in test
        pytest.fail(f"Failed to read file {path}: {exc}")


@dataclass
class ParsedModule:
    path: Path
    tree: ast.AST


def parse_module_safe(path: Path) -> Optional[ParsedModule]:
    try:
        code = path.read_text(encoding="utf-8")
    except Exception:
        return None
    try:
        return ParsedModule(path=path, tree=ast.parse(code, filename=str(path)))
    except SyntaxError:
        return None


def py_files_under(*roots: Path) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            files.append(p)
    return files


# 7.1.1 — Centralised AnswerKind enumeration
def test_7_1_1_centralised_answerkind_enumeration() -> None:
    """Verifies 7.1.1 — Centralised AnswerKind enumeration exists and matches schema."""
    # Assert: models/question_kind.py exists and defines QuestionKind constants
    qk_path = MODELS_DIR / "question_kind.py"
    assert qk_path.exists(), "app/models/question_kind.py must exist"
    pm = parse_module_safe(qk_path)
    assert pm is not None, "Failed to parse app/models/question_kind.py"

    expected_names = {
        "SHORT_STRING": "short_string",
        "LONG_TEXT": "long_text",
        "NUMBER": "number",
        "BOOLEAN": "boolean",
        "ENUM_SINGLE": "enum_single",
    }

    found: dict[str, str] = {}
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.ClassDef) and node.name == "QuestionKind":
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for tgt in stmt.targets:
                        if isinstance(tgt, ast.Name) and isinstance(getattr(stmt, "value", None), ast.Constant):
                            val = stmt.value.value  # type: ignore[attr-defined]
                            if isinstance(val, str):
                                found[tgt.id] = val
    assert expected_names.items() <= found.items(), (
        f"QuestionKind must define exact constants and values: expected {expected_names}, got {found}"
    )

    # Assert: schemas/AnswerKind.json exists and enum equals the five values (order-insensitive)
    ak_path = SCHEMAS_DIR / "AnswerKind.json"
    assert ak_path.exists(), "schemas/AnswerKind.json must exist"
    ak = read_json(ak_path)
    enum_vals = set(ak.get("enum") or [])
    assert enum_vals == set(expected_names.values()), (
        f"AnswerKind.json enum mismatch: expected {set(expected_names.values())}, got {enum_vals}"
    )


# 7.1.2 — Identifier schemas exist for entities
def test_7_1_2_identifier_schemas_exist() -> None:
    """Verifies 7.1.2 — Identifier schemas exist and declare $schema, $id, and titles."""
    targets = [
        SCHEMAS_DIR / "QuestionnaireId.schema.json",
        SCHEMAS_DIR / "ScreenId.schema.json",
        SCHEMAS_DIR / "question_id.schema.json",
    ]
    for p in targets:
        assert p.exists(), f"Schema file missing: {p}"
        data = read_json(p)
        # Assert: declares $schema and $id
        assert "$schema" in data and "$id" in data, f"Schema must declare $schema and $id: {p}"
        title = str(data.get("title", ""))
        # Title includes expected identifier names (case-insensitive)
        if p.name.lower().startswith("questionnaire"):
            assert "questionnaireid" in title.lower(), f"Title must include QuestionnaireId: {p}"
        elif p.name.lower().startswith("screen"):
            assert "screenid" in title.lower(), f"Title must include ScreenId: {p}"
        elif p.name.lower().startswith("question_") or "question" in p.name.lower():
            assert "question" in title.lower(), f"Title must include question_id/QuestionId: {p}"


# 7.1.3 — Persistence columns for question ordering and visibility
def test_7_1_3_persistence_columns_for_question_order_and_visibility() -> None:
    """Verifies 7.1.3 — DDL includes question_order, parent_question_id, visible_if_value."""
    init_sql = MIGRATIONS_DIR / "001_init.sql"
    add_order_sql = MIGRATIONS_DIR / "008_add_question_order.sql"
    assert init_sql.exists(), "migrations/001_init.sql must exist"
    text = read_text(init_sql).lower()

    # Assert: table questionnaire_question exists and has required columns
    assert "create table" in text and "questionnaire_question" in text, (
        "001_init.sql must define questionnaire_question table"
    )
    assert "question_order" in text, "questionnaire_question.question_order column must exist"
    assert "parent_question_id" in text, "questionnaire_question.parent_question_id column must exist"
    assert "visible_if_value" in text, "questionnaire_question.visible_if_value column must exist"

    # Assert: question_order defined as INT/INTEGER and NOT NULL
    # Simple regex: a line containing question_order followed by int/integer and NOT NULL
    line_matches = re.findall(r"question_order\s+(int|integer)[^\n]*not\s+null", text)
    assert line_matches, "question_order must be INT/INTEGER and NOT NULL in 001_init.sql"

    # Assert: 008_add_question_order.sql exists and includes ALTER TABLE ... ADD COLUMN IF NOT EXISTS question_order
    assert add_order_sql.exists(), "migrations/008_add_question_order.sql must exist"
    add_text = read_text(add_order_sql).lower()
    assert (
        "alter table" in add_text
        and "questionnaire_question" in add_text
        and "add column" in add_text
        and "if not exists" in add_text
        and "question_order" in add_text
    ), "008_add_question_order.sql must add question_order with IF NOT EXISTS"


# 7.1.4 — Screen ordering modeled in persistence
def test_7_1_4_screen_ordering_modeled_in_persistence() -> None:
    """Verifies 7.1.4 — A migration must declare a screen_order column for screens table."""
    # Search all *.sql under migrations for a declaration of screen_order
    any_sqls = list(MIGRATIONS_DIR.glob("*.sql"))
    assert any_sqls, "No migrations found; expected at least one for screen_order"
    found_decl = False
    for p in any_sqls:
        src = read_text(p).lower()
        if "screen_order" in src:
            # Heuristic: ensure it's a declaration context (CREATE TABLE or ADD COLUMN)
            if re.search(r"(create\s+table|add\s+column)[^\n]*screen_order", src):
                found_decl = True
                break
    assert found_decl, (
        "At least one migration must declare a screen_order column for screens; none found"
    )


# 7.1.5 — Centralised ETag helper module
def test_7_1_5_centralised_etag_helper() -> None:
    """Verifies 7.1.5 — app/logic/etag.py defines compute_screen_etag(response_set_id, screen_key)."""
    etag_path = LOGIC_DIR / "etag.py"
    assert etag_path.exists(), "app/logic/etag.py must exist"
    pm = parse_module_safe(etag_path)
    assert pm is not None, "Failed to parse app/logic/etag.py"
    has_sig = False
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.FunctionDef) and node.name == "compute_screen_etag":
            args = [a.arg for a in node.args.args]
            if args[:2] == ["response_set_id", "screen_key"]:
                has_sig = True
    assert has_sig, "compute_screen_etag(response_set_id, screen_key) must be defined in app/logic/etag.py"


# 7.1.6 — Repository layer present for screens and questionnaires
def test_7_1_6_repository_layer_present() -> None:
    """Verifies 7.1.6 — repository modules exist and expose list_/get_/count_ callables."""
    repos = [LOGIC_DIR / "repository_screens.py", LOGIC_DIR / "repository_questionnaires.py"]
    for rp in repos:
        assert rp.exists(), f"Repository module missing: {rp}"
        pm = parse_module_safe(rp)
        assert pm is not None, f"Failed to parse repository module: {rp}"
        src = read_text(rp)
        # Simple regex for def lines with allowed prefixes
        assert re.search(r"^def\s+(list_|get_|count_)\w+\(", src, re.MULTILINE), (
            f"Expected at least one list_/get_/count_ function in {rp}"
        )


# 7.1.7 — Route modules present for questionnaire/screen HTTP surfaces
def test_7_1_7_route_modules_present_and_define_api_routes() -> None:
    """Verifies 7.1.7 — route modules exist, define APIRouter, and have at least one '/api/' route."""
    files = [ROUTES_DIR / "questionnaires.py", ROUTES_DIR / "screens.py"]
    for p in files:
        assert p.exists(), f"Route module missing: {p}"
        pm = parse_module_safe(p)
        assert pm is not None, f"Failed to parse route module: {p}"
        # Assert: defines an APIRouter instance (Call to APIRouter())
        has_router = False
        for node in ast.walk(pm.tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
                if name == "APIRouter":
                    has_router = True
                    break
        assert has_router, f"Expected APIRouter() instantiation in {p}"

    # Assert: at least one route decorator path begins with "/api/"
    def module_has_api_route(pm: ParsedModule) -> bool:
        for node in ast.walk(pm.tree):
            if isinstance(node, ast.FunctionDef):
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
                        # router.get/post/patch(...)
                        if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
                            if dec.args[0].value.startswith("/api/"):
                                return True
        return False

    parsed = [parse_module_safe(p) for p in files]
    parsed = [pm for pm in parsed if pm is not None]  # type: ignore[assignment]
    assert any(module_has_api_route(pm) for pm in parsed if pm), (
        "At least one questionnaire/screen route path must begin with '/api/'"
    )


# 7.1.8 — Screen view schema exposes questions collection
def test_7_1_8_screen_view_schema_exposes_questions_array() -> None:
    """Verifies 7.1.8 — docs schema ScreenView has properties.questions array."""
    path = DOCS_SCHEMAS_DIR / "ScreenView.schema.json"
    assert path.exists(), f"Missing schema: {path}"
    data = read_json(path)
    props = data.get("properties", {})
    assert isinstance(props, dict) and "questions" in props, "ScreenView schema must declare properties.questions"
    questions = props.get("questions")
    assert isinstance(questions, dict) and questions.get("type") == "array", (
        "ScreenView.properties.questions must be of type 'array'"
    )


# 7.1.9 — OptionSpec schema present to support enum_single options
def test_7_1_9_option_spec_schema_present() -> None:
    """Verifies 7.1.9 — OptionSpec.json exists and declares $schema and 'OptionSpec' title."""
    path = SCHEMAS_DIR / "OptionSpec.json"
    assert path.exists(), f"Missing schema: {path}"
    data = read_json(path)
    assert "$schema" in data, "OptionSpec.json must declare $schema"
    assert "title" in data and "optionspec" in str(data.get("title")).lower(), (
        "OptionSpec.json title must include 'OptionSpec'"
    )


# 7.1.10 — Migrations runner present for deterministic evolution
def test_7_1_10_migrations_runner_present_and_imports_db() -> None:
    """Verifies 7.1.10 — migrations runner exists and imports app.db utilities."""
    path = DB_DIR / "migrations_runner.py"
    assert path.exists(), f"Missing migrations runner: {path}"
    src = read_text(path)
    assert (
        re.search(r"from\s+app\.db\b", src) or re.search(r"import\s+app\.db\b", src)
    ), "migrations_runner.py must import from app.db (engine/connection utility)"


# 7.1.11 — AGENTS.md present at repository root
def test_7_1_11_agents_md_present() -> None:
    """Verifies 7.1.11 — AGENTS.md present at repo root and mentions agents."""
    path = PROJECT_ROOT / "AGENTS.md"
    assert path.exists(), "AGENTS.md must exist at repository root"
    text = read_text(path)
    assert "Project overview" in text, "AGENTS.md must include 'Project overview'"
    assert any(name in text for name in ("Ada", "Clarke", "Hamilton")), (
        "AGENTS.md must mention at least one agent name"
    )


# 7.1.12 — Question identifier schema referenced consistently
def test_7_1_12_question_id_schema_referenced() -> None:
    """Verifies 7.1.12 — question_id.schema.json exists and is referenced via $ref elsewhere."""
    qid_path = SCHEMAS_DIR / "question_id.schema.json"
    assert qid_path.exists(), "schemas/question_id.schema.json must exist"

    # Scan other schemas for a $ref to question_id.schema.json
    referenced = False
    for path in SCHEMAS_DIR.glob("*.json"):
        if path.name == "question_id.schema.json":
            continue
        try:
            data = read_json(path)
        except Exception:
            continue
        # naive traversal for $ref strings
        def walk(obj: Any) -> None:
            nonlocal referenced
            if referenced:
                return
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == "$ref" and isinstance(v, str) and "question_id.schema.json" in v:
                        referenced = True
                        return
                    walk(v)
            elif isinstance(obj, list):
                for it in obj:
                    walk(it)

        walk(data)

    assert referenced, "At least one other schema must $ref question_id.schema.json"


# 7.1.13 — AnswerKind values consistent between code and schema
def test_7_1_13_answerkind_values_consistent() -> None:
    """Verifies 7.1.13 — QuestionKind constants equal AnswerKind.json enum values (order-insensitive)."""
    # Extract from code
    qk_path = MODELS_DIR / "question_kind.py"
    assert qk_path.exists(), "app/models/question_kind.py must exist"
    pm = parse_module_safe(qk_path)
    assert pm is not None, "Failed to parse app/models/question_kind.py"
    code_vals: set[str] = set()
    for node in ast.walk(pm.tree):
        if isinstance(node, ast.ClassDef) and node.name == "QuestionKind":
            for stmt in node.body:
                if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant) and isinstance(stmt.value.value, str):
                    code_vals.add(stmt.value.value)
    # Extract from schema
    ak_path = SCHEMAS_DIR / "AnswerKind.json"
    assert ak_path.exists(), "schemas/AnswerKind.json must exist"
    schema_vals = set(read_json(ak_path).get("enum") or [])
    assert code_vals == schema_vals and len(code_vals) > 0, (
        f"AnswerKind values mismatch between code and schema: {code_vals} vs {schema_vals}"
    )


# 7.1.14 — Visibility-related persistence fields present
def test_7_1_14_visibility_persistence_fields_present() -> None:
    """Verifies 7.1.14 — parent_question_id and visible_if_value present; visible_if_value is JSON/JSONB."""
    init_sql = MIGRATIONS_DIR / "001_init.sql"
    assert init_sql.exists(), "migrations/001_init.sql must exist"
    src = read_text(init_sql).lower()
    # Table and columns present
    assert "questionnaire_question" in src, "questionnaire_question table must exist"
    assert "parent_question_id" in src, "parent_question_id column must exist on questionnaire_question"
    assert "visible_if_value" in src, "visible_if_value column must exist on questionnaire_question"
    # visible_if_value typed as json/jsonb
    assert re.search(r"visible_if_value\s+(json|jsonb)\b", src) is not None, (
        "visible_if_value must be typed as JSON/JSONB"
    )


# 7.1.15 — Ordering artefacts isolated from UI route modules
def test_7_1_15_ordering_artifacts_not_in_routes() -> None:
    """Verifies 7.1.15 — Route modules do not implement ordering logic or touch order fields directly."""
    files = [ROUTES_DIR / "questionnaires.py", ROUTES_DIR / "screens.py"]
    for p in files:
        assert p.exists(), f"Route module missing: {p}"
        text = read_text(p).lower()
        # No functions named with reindex/reorder/contiguous
        assert not re.search(r"def\s+.*(reindex|reorder|contiguous)", text), (
            f"Route module must not define reindex/reorder/contiguous functions: {p}"
        )
        # No raw SQL touching order fields via execute(...) or text(...)
        assert not re.search(
            r"(execute|text)\s*\([^)]*(question_order|screen_order)", text, re.DOTALL
        ), f"Route module must not issue raw SQL touching order fields: {p}"


# 7.1.16 — Migrations journal tracked
def test_7_1_16_migrations_journal_tracked() -> None:
    """Verifies 7.1.16 — migrations/_journal.json exists, valid JSON, and non-empty."""
    path = MIGRATIONS_DIR / "_journal.json"
    assert path.exists(), "migrations/_journal.json must exist"
    data = read_json(path)
    ok = False
    if isinstance(data, list) and len(data) > 0:
        ok = True
    if isinstance(data, dict) and len(data) > 0:
        ok = True
    assert ok, "_journal.json must contain at least one entry (list or object)"

