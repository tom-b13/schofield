"""Architectural tests for EPIC-A — Data model & migrations (Section 7.1).

These tests enforce the architectural assertions defined in:
docs/Epic A - Data model & migration.md, section 7.1.

Each test corresponds to a 7.1.x subsection and validates only the
assertions listed for that subsection. Tests use file-system and text/AST
inspection only to avoid executing application code.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set, Tuple


DOCS = Path("docs")
MIGRATIONS = Path("migrations")
CONFIG = Path("config")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception as exc:  # pragma: no cover - defensive path
        raise AssertionError(f"Failed to read text file: {path}: {exc}")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(_read_text(path))
    except Exception as exc:  # pragma: no cover - defensive path
        raise AssertionError(f"Failed to parse JSON: {path}: {exc}")


def _read_csv_rows(path: Path) -> List[List[str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as fh:
            return [row for row in csv.reader(fh)]
    except Exception as exc:  # pragma: no cover - defensive path
        raise AssertionError(f"Failed to read CSV: {path}: {exc}")


def _extract_create_table_columns(sql: str) -> Dict[str, Set[str]]:
    """Best-effort SQL introspection for CREATE TABLE column names.

    Returns mapping: table_name -> set(column_names)
    """
    tables: Dict[str, Set[str]] = {}
    # Rough pattern: CREATE TABLE table_name ( ... );
    for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s*\((.*?)\);",
                         sql, re.IGNORECASE | re.DOTALL):
        table = m.group(1)
        cols_block = m.group(2)
        # Split columns/constraints by commas at top level
        parts = [p.strip() for p in re.split(r",\s*(?![^()]*\))", cols_block) if p.strip()]
        colnames: Set[str] = set()
        for p in parts:
            # Column definition typically starts with identifier
            cm = re.match(r"(\w+)\s+", p)
            if cm:
                colnames.add(cm.group(1))
        tables[table] = colnames
    return tables


def _find_fk_defs(sql: str) -> List[str]:
    return re.findall(r"FOREIGN\s+KEY\s*\(([^)]*)\)\s+REFERENCES\s+(\w+)\s*\(([^)]*)\)", sql, re.IGNORECASE)


def _find_unique_defs(sql: str) -> List[str]:
    return re.findall(r"\bUNIQUE\b\s*\(([^)]*)\)", sql, re.IGNORECASE)


def _find_unique_index_defs(sql: str) -> List[str]:
    return re.findall(r"CREATE\s+UNIQUE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON\s+(\w+)\s*\(([^)]*)\)(?:\s+WHERE\s+(.+?))?;",
                      sql, re.IGNORECASE | re.DOTALL)


def _collect_erd_constraint_names(erd: Dict[str, Any]) -> Set[str]:
    """Collect constraint identifiers declared in the ERD.

    Includes names from: primary_key.name, foreign_keys[*].name, unique[*].name, checks[*].name
    """
    names: Set[str] = set()
    for ent in erd.get("entities", []) or []:
        if not isinstance(ent, dict):
            continue
        pk = ent.get("primary_key")
        if isinstance(pk, dict):
            nm = pk.get("name")
            if isinstance(nm, str) and nm.strip():
                names.add(nm)
        for key in ("foreign_keys", "unique", "checks"):
            for obj in ent.get(key, []) or []:
                if isinstance(obj, dict):
                    nm = obj.get("name")
                    if isinstance(nm, str) and nm.strip():
                        names.add(nm)
    return names


def _collect_sql_constraint_like_names(sql: str) -> Set[str]:
    """Collect identifiers declared in constraints SQL.

    Captures: named CONSTRAINT <name> ... and CREATE UNIQUE INDEX <name> ...
    """
    names: Set[str] = set()
    for m in re.finditer(r"\bCONSTRAINT\s+(\w+)\b", sql, re.IGNORECASE):
        names.add(m.group(1))
    for m in re.finditer(r"CREATE\s+UNIQUE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", sql, re.IGNORECASE):
        names.add(m.group(1))
    return names


def _collect_created_objects_from_migrations() -> List[Tuple[str, str]]:
    """Return created objects in creation order across 001–003.

    Each item is (kind, name) where kind in {"table", "constraint", "index"}.
    Order: 001 tables (file order), then 002 constraints/unique indexes (file order), then 003 indexes (file order).
    """
    created: List[Tuple[str, str]] = []
    # 001: tables
    sql_001 = _read_text(MIGRATIONS / "001_init.sql")
    for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", sql_001, re.IGNORECASE):
        created.append(("table", m.group(1).lower()))
    # 002: constraints and unique indexes in file order
    sql_002 = _read_text(MIGRATIONS / "002_constraints.sql")
    events: List[Tuple[int, str, str]] = []  # (pos, kind, name)
    for m in re.finditer(r"\bCONSTRAINT\s+(\w+)\b", sql_002, re.IGNORECASE):
        events.append((m.start(), "constraint", m.group(1)))
    for m in re.finditer(r"CREATE\s+UNIQUE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", sql_002, re.IGNORECASE):
        events.append((m.start(), "index", m.group(1)))
    events.sort(key=lambda x: x[0])
    created.extend([(k, n.lower()) for _, k, n in events])
    # 003: indexes in file order
    sql_003 = _read_text(MIGRATIONS / "003_indexes.sql")
    for m in re.finditer(r"CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", sql_003, re.IGNORECASE):
        created.append(("index", m.group(1).lower()))
    return created


def _ddl_tokens_present_outside_migrations() -> List[Tuple[Path, str]]:
    tokens = [
        r"\bCREATE\s+TABLE\b",
        r"\bALTER\s+TABLE\b",
        r"\bCREATE\s+INDEX\b",
        r"\bCONSTRAINT\b",
    ]
    offenders: List[Tuple[Path, str]] = []
    for path in Path(".").rglob("*.py"):
        # Skip virtualenvs or hidden folders if any. Robustly skip top-level migrations/ and tests/ trees.
        rel = path.as_posix().lstrip("./")
        if rel.startswith("migrations/"):
            continue
        # Exclude tests from scan; only application code should be checked
        if rel.startswith("tests/"):
            continue
        # Exclude common hidden/virtualenv dirs to avoid false positives
        if rel.startswith((".venv/", ".git/", ".pytest_cache/")):
            continue
        # Robustly exclude any paths that include virtualenv or site-packages directories
        parts = set(path.parts)
        if any(p in {"venv", ".venv", "site-packages", "dist-packages"} for p in parts):
            continue
        try:
            text = _read_text(path)
        except AssertionError:
            continue
        for t in tokens:
            if re.search(t, text, re.IGNORECASE):
                offenders.append((path, t))
                break
    return offenders


# 7.1.1 — Entities Declared with Canonical Names
def test_entities_declared_with_canonical_names() -> None:
    """Verifies 7.1.1 — entities are uniquely and canonically named."""
    erd_path = DOCS / "erd_spec.json"

    # File exists and parses as JSON.
    assert erd_path.exists(), "docs/erd_spec.json must exist"
    erd = _read_json(erd_path)

    entities = erd.get("entities")
    assert isinstance(entities, list), "`entities` must be an array of entity objects"

    names: List[str] = []
    for i, ent in enumerate(entities):
        assert isinstance(ent, dict), f"entities[{i}] must be an object"
        assert "name" in ent, f"entities[{i}] must include `name`"
        assert isinstance(ent["name"], str) and ent["name"].strip(), "Entity name must be non-empty string"
        names.append(ent["name"])

    assert len(names) == len(set(names)), "Entity names must be unique"


# 7.1.2 — Per-Entity Field List Is Explicit
def test_entities_declare_explicit_field_collections() -> None:
    """Verifies 7.1.2 — each entity declares fields[] with name and type."""
    erd = _read_json(DOCS / "erd_spec.json")
    entities = erd.get("entities")
    assert isinstance(entities, list), "`entities` must be an array"

    for i, ent in enumerate(entities):
        fields = ent.get("fields")
        assert isinstance(fields, list), f"entities[{i}].fields must be an array"
        assert fields, f"entities[{i}].fields must not be empty"
        for j, f in enumerate(fields):
            assert isinstance(f, dict), f"entities[{i}].fields[{j}] must be an object"
            assert isinstance(f.get("name"), str) and f["name"].strip(), "Field name must be non-empty string"
            assert isinstance(f.get("type"), str) and f["type"].strip(), "Field type must be non-empty string"


# 7.1.3 — No Duplicate Field Names Within an Entity
def test_entity_field_names_are_unique_per_entity() -> None:
    """Verifies 7.1.3 — no duplicate field names within an entity."""
    erd = _read_json(DOCS / "erd_spec.json")
    for i, ent in enumerate(erd.get("entities", [])):
        assert isinstance(ent.get("fields"), list), f"entities[{i}].fields must be an array"
        names = [f.get("name") for f in ent["fields"]]
        assert all(isinstance(n, str) for n in names), f"entities[{i}].fields[*].name must be strings"
        assert len(names) == len(set(names)), f"entities[{i}] must not contain duplicate field names"


# 7.1.4 — Field Types Align With ERD
def test_migration_column_types_match_erd_types() -> None:
    """Verifies 7.1.4 — migration column types correspond to ERD field types."""
    erd = _read_json(DOCS / "erd_spec.json")
    sql_path = MIGRATIONS / "001_init.sql"
    assert sql_path.exists(), "migrations/001_init.sql must exist"
    sql = _read_text(sql_path)
    tables = _extract_create_table_columns(sql)

    for ent in erd.get("entities", []):
        assert isinstance(ent.get("name"), str) and ent["name"].strip(), "Entity must have name"
        assert isinstance(ent.get("fields"), list), f"Entity {ent.get('name')} must declare fields[]"
        # Verify column exists for each field; basic type token presence check
        for f in ent["fields"]:
            fname = f.get("name")
            ftype = f.get("type")
            assert fname and ftype, "Each field must have name and type"
            # Use snake_case table name derived from CamelCase entity name
            table = re.sub(r"(?<!^)(?=[A-Z])", "_", ent["name"]).lower()
            assert table in tables, f"CREATE TABLE missing for entity {ent['name']}"
            assert fname in tables[table], f"Column {fname} missing in table {table}"
            # Type token appears on the column definition line anywhere in file
            # Allow types that end with non-word characters (e.g., char(64)) by using a non-word lookahead
            pattern = rf"\b{re.escape(table)}\b\s*\([^;]*\b{re.escape(fname)}\b\s+{re.escape(ftype)}(?!\w)"
            assert re.search(pattern, sql, re.IGNORECASE | re.DOTALL), (
                f"Column {table}.{fname} must have type {ftype} in 001_init.sql"
            )


# 7.1.5 — Encryption Flag Present Where Required
def test_sensitive_fields_include_encrypted_boolean() -> None:
    """Verifies 7.1.5 — sensitive fields include `encrypted` boolean and values are correct."""
    erd = _read_json(DOCS / "erd_spec.json")
    for ent in erd.get("entities", []):
        fields = ent.get("fields")
        assert isinstance(fields, list), "fields must be an array of objects"
        for f in fields:
            if f.get("sensitive") is True:
                assert "encrypted" in f and isinstance(f["encrypted"], bool), (
                    f"Sensitive field {ent.get('name')}.{f.get('name')} must declare boolean `encrypted`"
                )
                assert f["encrypted"] is True, (
                    f"Sensitive field {ent.get('name')}.{f.get('name')} must set encrypted: true"
                )


# 7.1.6 — Primary Key Columns Listed Structurally
def test_entities_declare_primary_key_columns_structurally() -> None:
    """Verifies 7.1.6 — PKs declare primary_key.columns[] present and valid."""
    erd = _read_json(DOCS / "erd_spec.json")
    for ent in erd.get("entities", []):
        if ent.get("primary_key"):
            pk = ent["primary_key"]
            cols = pk.get("columns") if isinstance(pk, dict) else None
            assert isinstance(cols, list) and cols, (
                f"Entity {ent.get('name')} must declare primary_key.columns as non-empty array"
            )
            field_names = {f.get("name") for f in ent.get("fields", []) if isinstance(f, dict)}
            for c in cols:
                assert c in field_names, f"PK column {c} must exist in fields of {ent.get('name')}"


# 7.1.7 — Foreign Keys Modelled With Names, Columns, and References
def test_foreign_keys_modelled_and_present_in_ddl() -> None:
    """Verifies 7.1.7 — FK objects complete in ERD and present in SQL."""
    erd = _read_json(DOCS / "erd_spec.json")
    sql_path = MIGRATIONS / "002_constraints.sql"
    assert sql_path.exists(), "migrations/002_constraints.sql must exist"
    sql = _read_text(sql_path)

    for ent in erd.get("entities", []):
        for fk in ent.get("foreign_keys", []):
            assert isinstance(fk.get("name"), str) and fk["name"].strip(), "FK must have name"
            assert isinstance(fk.get("columns"), list) and fk["columns"], "FK must have columns[]"
            ref = fk.get("references")
            assert isinstance(ref, dict), "FK must have references object"
            assert isinstance(ref.get("entity"), str) and ref["entity"].strip(), "FK references.entity required"
            assert isinstance(ref.get("columns"), list) and ref["columns"], "FK references.columns[] required"

            # Check DDL contains matching FK (best-effort by column names)
            cols = ",".join(fk["columns"]).lower()
            refcols = ",".join(ref["columns"]).lower()
            assert any(
                cols == c.replace(" ", "").lower()
                and re.sub(r"(?<!^)(?=[A-Z])", "_", ref["entity"]).lower() == t.lower()
                and refcols == rc.replace(" ", "").lower()
                for c, t, rc in _find_fk_defs(sql)
            ), f"FK {fk['name']} missing in 002_constraints.sql"


# 7.1.8 — Unique Constraints Declared With Name and Columns
def test_unique_constraints_declared_and_present_in_ddl() -> None:
    """Verifies 7.1.8 — uniques have name and columns and exist in SQL."""
    erd = _read_json(DOCS / "erd_spec.json")
    sql = _read_text(MIGRATIONS / "002_constraints.sql")
    uniques_in_sql = [u.replace(" ", "").lower() for u in _find_unique_defs(sql)]
    # Include CREATE UNIQUE INDEX definitions as unique column sets as well
    uniques_in_sql += [
        cols.replace(" ", "").lower()
        for _, _, cols, _ in _find_unique_index_defs(sql)
    ]

    for ent in erd.get("entities", []):
        for uq in ent.get("unique", []):
            assert isinstance(uq.get("name"), str) and uq["name"].strip(), "Unique must have name"
            assert isinstance(uq.get("columns"), list) and uq["columns"], "Unique must have columns[]"
            cols = ",".join(uq["columns"]).replace(" ", "").lower()
            assert any(cols == u for u in uniques_in_sql), (
                f"Unique {uq['name']} with columns {cols} missing in 002_constraints.sql"
            )


# 7.1.9 — Secondary Indexes Declared With Name and Columns
def test_indexes_declared_and_created_by_migrations() -> None:
    """Verifies 7.1.9 — indexes have name and columns and exist in 003."""
    erd = _read_json(DOCS / "erd_spec.json")
    sql = _read_text(MIGRATIONS / "003_indexes.sql")
    create_index_cols = [
        (m.group(1).lower(), m.group(2).lower(), m.group(3).replace(" ", "").lower())
        for m in re.finditer(
            r"CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)\s+ON\s+(\w+)\s*\(([^)]*)\);",
            sql, re.IGNORECASE)
    ]
    for ent in erd.get("entities", []):
        for ix in ent.get("indexes", []):
            assert isinstance(ix.get("name"), str) and ix["name"].strip(), "Index must have name"
            assert isinstance(ix.get("columns"), list) and ix["columns"], "Index must have columns[]"
            cols = ",".join(ix["columns"]).replace(" ", "").lower()
            # Use snake_case table name derived from CamelCase entity name
            table = re.sub(r"(?<!^)(?=[A-Z])", "_", ent["name"]).lower()
            assert any(cols == c and table == t for _, t, c in create_index_cols), (
                f"Index {ix['name']} missing in 003_indexes.sql"
            )


# 7.1.10 — Enumerations Declared Centrally
def test_enums_centralised_with_names_and_values() -> None:
    """Verifies 7.1.10 — ERD includes enums[] with name and values, and SQL defines them."""
    erd = _read_json(DOCS / "erd_spec.json")
    assert isinstance(erd.get("enums"), list) and erd["enums"], "ERD must include enums[] with entries"
    for i, e in enumerate(erd["enums"]):
        assert isinstance(e.get("name"), str) and e["name"].strip(), f"enums[{i}].name required"
        assert isinstance(e.get("values"), list) and e["values"], f"enums[{i}].values[] required"

    sql = _read_text(MIGRATIONS / "001_init.sql")
    for e in erd["enums"]:
        # Check enum type and its values are present in DDL (best-effort).
        assert re.search(rf"\bTYPE\s+{re.escape(e['name'])}\b", sql, re.IGNORECASE), (
            f"Enum type {e['name']} must be defined in 001_init.sql"
        )
        for v in e["values"]:
            assert v in sql, f"Enum value {v} must appear in 001_init.sql for {e['name']}"


# 7.1.11 — Global Encrypted Field Manifest Exists
def test_global_encrypted_field_manifest_exists() -> None:
    """Verifies 7.1.11 — encrypted_fields[] manifest exists and is complete."""
    erd = _read_json(DOCS / "erd_spec.json")
    manifest = erd.get("encrypted_fields")
    assert isinstance(manifest, list), "encrypted_fields[] manifest must exist"
    # Build set from entities where encrypted: true
    expected: Set[str] = set()
    for ent in erd.get("entities", []):
        for f in ent.get("fields", []) or []:
            if isinstance(f, dict) and f.get("encrypted") is True:
                expected.add(f"{ent.get('name')}.{f.get('name')}")
    # Every encrypted field must appear exactly once
    assert set(manifest) == expected, "encrypted_fields[] must exactly list all encrypted fields"


# 7.1.12 — Global Constraint Manifest Exists
def test_global_constraints_manifest_exists() -> None:
    """Verifies 7.1.12 — constraints_applied[] enumerates all applied constraints comprehensively.

    Asserts non-empty, string-only, and equals the union of identifiers declared in ERD and constraints SQL.
    """
    erd = _read_json(DOCS / "erd_spec.json")
    manifest = erd.get("constraints_applied")
    assert isinstance(manifest, list), "constraints_applied[] must exist"
    assert manifest, "constraints_applied[] must be non-empty"
    assert all(isinstance(x, str) and x.strip() for x in manifest), "All constraint identifiers must be strings"

    # Collect expected identifiers from ERD (PK/FK/UNIQUE/CHECK names)
    erd_names = _collect_erd_constraint_names(erd)

    # Collect identifiers from constraints SQL (named CONSTRAINTs, CREATE UNIQUE INDEX names)
    sql_constraints_path = MIGRATIONS / "002_constraints.sql"
    assert sql_constraints_path.exists(), "migrations/002_constraints.sql must exist"
    sql_constraints_text = _read_text(sql_constraints_path)
    sql_names = _collect_sql_constraint_like_names(sql_constraints_text)

    expected_union = erd_names.union(sql_names)
    # Must contain at least all ERD-declared identifiers, and ideally match the union
    missing = erd_names.difference(set(manifest))
    assert not missing, f"constraints_applied[] missing ERD-declared identifiers: {sorted(missing)}"
    assert set(manifest) == expected_union, (
        "constraints_applied[] must equal the union of ERD and SQL-declared identifiers"
    )


# 7.1.13 — Migration Journal Structure is Stable
def test_migration_journal_structure_is_stable() -> None:
    """Verifies 7.1.13 — journal file exists and entries have filename/applied_at."""
    # Allow multiple possible locations; require at least one present
    candidates = [MIGRATIONS / "_journal.json", Path("_journal.json")] 
    present = [p for p in candidates if p.exists()]
    assert present, "Migration journal artefact must exist (e.g., migrations/_journal.json)"
    journal = _read_json(present[0])
    assert isinstance(journal, list) and journal, "Journal must be a non-empty array"
    for i, entry in enumerate(journal):
        assert isinstance(entry, dict), f"Journal entry {i} must be an object"
        assert isinstance(entry.get("filename"), str) and entry["filename"].strip(), "filename required"
        assert isinstance(entry.get("applied_at"), str) and entry["applied_at"].strip(), "applied_at required"
        # ISO-8601 UTC basic check
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", entry["applied_at"]), (
            "applied_at must be ISO-8601 UTC (e.g., 2024-01-01T00:00:00Z)"
        )


# 7.1.14 — Deterministic Ordering of Collections
def test_collections_are_in_deterministic_sorted_order() -> None:
    """Verifies 7.1.14 — collections are deterministically ordered in ERD and parity exports."""
    erd = _read_json(DOCS / "erd_spec.json")
    mermaid = _read_text(DOCS / "erd_mermaid.md")
    rel_rows = _read_csv_rows(DOCS / "erd_relationships.csv")

    # Entities sorted by canonical name
    entities = [e.get("name", "") for e in erd.get("entities", [])]
    assert entities == sorted(entities), "ERD entities should be sorted by name deterministically"

    # Fields sorted by field name within each entity
    for ent in erd.get("entities", []) or []:
        fields = ent.get("fields", []) or []
        names = [f.get("name", "") for f in fields if isinstance(f, dict)]
        assert names == sorted(names), f"Fields must be sorted by name for entity {ent.get('name')}"

    # Unique constraints, foreign keys, and indexes lists sorted by their canonical names
    for ent in erd.get("entities", []) or []:
        for key in ("unique", "foreign_keys", "indexes"):
            items = ent.get(key, []) or []
            if not items:
                continue
            names = [i.get("name", "") for i in items if isinstance(i, dict)]
            assert names == sorted(names), f"{key} must be sorted by name for entity {ent.get('name')}"

    # Mermaid nodes appear in sorted order by name (best-effort)
    node_lines = [ln for ln in mermaid.splitlines() if ln.strip().startswith("class ") or ln.strip().startswith("table ")]
    names_in_mermaid = [re.findall(r"\b(class|table)\s+(\w+)", ln)[0][1] for ln in node_lines] if node_lines else []
    if names_in_mermaid:
        assert names_in_mermaid == sorted(names_in_mermaid), "Mermaid nodes must be listed in sorted order"

    # Mermaid edges sorted deterministically by (source, target)
    edge_pairs_in_order: List[Tuple[str, str]] = []
    for line in mermaid.splitlines():
        m = re.search(r"(\w+)\s*[-.]{2,}>\s*(\w+)", line)
        if m:
            edge_pairs_in_order.append((m.group(1), m.group(2)))
    if edge_pairs_in_order:
        assert edge_pairs_in_order == sorted(edge_pairs_in_order), "Mermaid edges must be sorted by (source,target)"

    # CSV rows deterministically sorted by (source, target) after header
    assert rel_rows, "relationships CSV must be present"
    header = [h.strip().lower() for h in rel_rows[0]]
    try:
        src_idx = header.index("source")
        dst_idx = header.index("target")
    except ValueError:
        # Fallback to first two columns
        src_idx, dst_idx = 0, 1
    pairs = [(r[src_idx].strip(), r[dst_idx].strip()) for r in rel_rows[1:] if len(r) > max(src_idx, dst_idx)]
    if pairs:
        assert pairs == sorted(pairs), "CSV relationships must be sorted by (source,target)"


# 7.1.15 — Placeholder Lookup Artefacts Are Present
def test_placeholder_lookup_artifacts_are_present() -> None:
    """Verifies 7.1.15 — direct lookup placeholder artifacts exist and no legacy join artefacts."""
    erd = _read_json(DOCS / "erd_spec.json")
    # ERD includes QuestionnaireQuestion with optional placeholder_code field
    qq = next((e for e in erd.get("entities", []) if e.get("name") == "QuestionnaireQuestion"), None)
    assert qq is not None, "ERD must include entity QuestionnaireQuestion"
    fields = {f.get("name") for f in (qq.get("fields") or []) if isinstance(f, dict)}
    assert "placeholder_code" in fields, "QuestionnaireQuestion must include optional placeholder_code field"

    # Partial unique on QuestionnaireQuestion(placeholder_code) where not null
    sql = _read_text(MIGRATIONS / "002_constraints.sql")
    assert re.search(r"CREATE\s+UNIQUE\s+INDEX[\s\S]*ON\s+questionnaire_question\s*\(\s*placeholder_code\s*\)\s*WHERE\s+placeholder_code\s+IS\s+NOT\s+NULL",
                    sql, re.IGNORECASE), "Partial unique on QuestionnaireQuestion(placeholder_code) must exist"

    # No TemplatePlaceholder or QuestionToPlaceholder entities or DDL
    erd_entity_names = {e.get("name") for e in erd.get("entities", [])}
    assert "TemplatePlaceholder" not in erd_entity_names and "QuestionToPlaceholder" not in erd_entity_names, (
        "ERD must not contain TemplatePlaceholder or QuestionToPlaceholder"
    )
    ddl_all = _read_text(MIGRATIONS / "001_init.sql") + "\n" + sql
    assert re.search(r"\btemplate_placeholder\b", ddl_all, re.IGNORECASE) is None
    assert re.search(r"\bquestion_to_placeholder\b", ddl_all, re.IGNORECASE) is None


# 7.1.16 — Constraint Rules Enforced Structurally
def test_structural_constraints_for_responses_and_placeholders() -> None:
    """Verifies 7.1.16 — one-response-per-question-per-submission and no duplicate placeholders."""
    erd = _read_json(DOCS / "erd_spec.json")
    sql = _read_text(MIGRATIONS / "002_constraints.sql")

    # ERD defines composite unique on Response(response_set_id, question_id)
    response = next((e for e in erd.get("entities", []) if e.get("name") == "Response"), None)
    assert response is not None, "ERD must include entity Response"
    uniques = response.get("unique") or []
    assert any(u.get("columns") == ["response_set_id", "question_id"] for u in uniques if isinstance(u, dict)), (
        "ERD must define composite unique on Response(response_set_id, question_id)"
    )

    # 002_constraints.sql contains matching UNIQUE
    assert re.search(r"UNIQUE\s*\(\s*response_set_id\s*,\s*question_id\s*\)", sql, re.IGNORECASE), (
        "002_constraints.sql must contain matching UNIQUE(response_set_id, question_id)"
    )

    # ERD/migrations encode no duplicate placeholders via partial unique on QuestionnaireQuestion(placeholder_code)
    qq = next((e for e in erd.get("entities", []) if e.get("name") == "QuestionnaireQuestion"), None)
    assert qq is not None, "ERD must include entity QuestionnaireQuestion"
    assert re.search(r"CREATE\s+UNIQUE\s+INDEX[\s\S]*ON\s+questionnaire_question\s*\(\s*placeholder_code\s*\)\s*WHERE\s+placeholder_code\s+IS\s+NOT\s+NULL",
                    sql, re.IGNORECASE), "Partial unique on QuestionnaireQuestion(placeholder_code) must exist"


# 7.1.17 — TLS Requirement Exposed as Configuration
def test_tls_requirement_exposed_as_configuration() -> None:
    """Verifies 7.1.17 — configuration key for TLS enforcement exists and is boolean."""
    key_path = CONFIG / "database.ssl.required"
    assert key_path.exists(), "config/database.ssl.required must exist"
    value = _read_text(key_path).strip().lower()
    assert value in {"true", "false"}, "config/database.ssl.required must be boolean text ('true' or 'false')"


# 7.1.18 — Column-Level Encryption is Configurable
def test_column_level_encryption_is_configurable() -> None:
    """Verifies 7.1.18 — encryption.mode allowed values; kms.key_alias required when mode includes column."""
    mode_path = CONFIG / "encryption.mode"
    assert mode_path.exists(), "config/encryption.mode must exist"
    mode = _read_text(mode_path).strip()
    assert mode in {"tde", "column", "tde+column"}, "encryption.mode must be one of: tde, column, tde+column"
    if "column" in mode:
        alias_path = CONFIG / "kms.key_alias"
        assert alias_path.exists(), "config/kms.key_alias must exist when mode includes 'column'"
        assert _read_text(alias_path).strip(), "config/kms.key_alias must be non-empty"


# 7.1.19 — ERD Sources Versioned as Project Artefacts
def test_erd_sources_versioned_as_project_artifacts() -> None:
    """Verifies 7.1.19 — ERD JSON and parity docs exist and are readable with non-empty content."""
    erd = _read_json(DOCS / "erd_spec.json")
    assert isinstance(erd, dict) and erd, "docs/erd_spec.json must parse as non-empty JSON object"

    mermaid = _read_text(DOCS / "erd_mermaid.md")
    assert isinstance(mermaid, str) and mermaid.strip(), "docs/erd_mermaid.md must be readable and non-empty"

    rows = _read_csv_rows(DOCS / "erd_relationships.csv")
    assert isinstance(rows, list) and rows, "docs/erd_relationships.csv must be readable and non-empty"


# 7.1.20 — Rollback Scripts Present and Ordered
def test_rollback_scripts_present_and_reverse_prior_migrations() -> None:
    """Verifies 7.1.20 — rollback script reverses objects in strict reverse creation order."""
    rb_path = MIGRATIONS / "004_rollbacks.sql"
    assert rb_path.exists(), "migrations/004_rollbacks.sql must exist"
    rb_sql = _read_text(rb_path)

    # Keep presence check for table drops
    created_tables_aggregate = (
        [m.group(1).lower() for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(\w+)", _read_text(MIGRATIONS / "001_init.sql"), re.IGNORECASE)]
    )
    for t in set(created_tables_aggregate):
        assert re.search(rf"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?{re.escape(t)}\b", rb_sql, re.IGNORECASE), (
            f"Rollback must drop table: {t}"
        )

    # Extract created objects in order and ensure DROP statements follow strict reverse order
    created_objects = _collect_created_objects_from_migrations()
    assert created_objects, "No created objects detected from 001–003; check migrations present"

    def _drop_pos(kind: str, name: str) -> int:
        if kind == "table":
            pat = rf"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?{re.escape(name)}\b"
        elif kind == "index":
            pat = rf"DROP\s+INDEX\s+(?:IF\s+EXISTS\s+)?{re.escape(name)}\b"
        elif kind == "constraint":
            pat = rf"DROP\s+CONSTRAINT\s+(?:IF\s+EXISTS\s+)?{re.escape(name)}\b"
        else:
            pat = None
        if not pat:
            return -1
        m = re.search(pat, rb_sql, re.IGNORECASE)
        assert m is not None, f"Rollback must drop {kind} named {name}"
        return m.start()

    positions = [_drop_pos(k, n) for k, n in reversed(created_objects)]
    # Strictly increasing positions imply reverse creation order in rollback
    assert all(earlier < later for earlier, later in zip(positions, positions[1:])), (
        "Rollback drops must be ordered strictly as reverse of creation order for 001–003"
    )


# 7.1.21 — Generated Document Storage is Modelled
def test_generated_document_storage_is_modelled() -> None:
    """Verifies 7.1.21 — model contains generated document entity with id and output_uri; DDL present."""
    erd = _read_json(DOCS / "erd_spec.json")
    gen = next((e for e in erd.get("entities", []) if e.get("name") == "GeneratedDocument"), None)
    assert gen is not None, "ERD must include entity GeneratedDocument"
    fields = {f.get("name") for f in (gen.get("fields") or []) if isinstance(f, dict)}
    assert "generated_document_id" in fields or "id" in fields, "GeneratedDocument must have stable identifier field"
    assert "output_uri" in fields, "GeneratedDocument must include output_uri field"

    sql = _read_text(MIGRATIONS / "001_init.sql")
    assert re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?generated_document\b", sql, re.IGNORECASE), "DDL must create generated_document table"
    assert re.search(r"\bgenerated_document\b[\s\S]*\boutput_uri\b", sql, re.IGNORECASE), "DDL must include output_uri column"


# 7.1.24 — Deterministic Lookup Contracts Are Encoded in Keys
def test_lookup_contracts_are_encoded_in_keys() -> None:
    """Verifies 7.1.24 — partial unique on placeholder_code and supporting response indexes."""
    sql2 = _read_text(MIGRATIONS / "002_constraints.sql")
    sql3 = _read_text(MIGRATIONS / "003_indexes.sql")

    assert re.search(r"CREATE\s+UNIQUE\s+INDEX[\s\S]*ON\s+questionnaire_question\s*\(\s*placeholder_code\s*\)\s*WHERE\s+placeholder_code\s+IS\s+NOT\s+NULL",
                    sql2, re.IGNORECASE), "Partial unique on QuestionnaireQuestion(placeholder_code) must exist"
    assert re.search(r"CREATE\s+INDEX[\s\S]*ON\s+response\s*\(\s*response_set_id\s*\)", sql3, re.IGNORECASE), (
        "Supporting index on Response(response_set_id) must exist"
    )
    assert re.search(r"CREATE\s+INDEX[\s\S]*ON\s+response\s*\(\s*question_id\s*\)", sql3, re.IGNORECASE), (
        "Supporting index on Response(question_id) must exist"
    )


# 7.1.25 — Encryption at Rest Policy is Traceable to Columns
def test_encrypted_fields_trace_to_global_manifest() -> None:
    """Verifies 7.1.25 — Entity.field set for encrypted columns equals encrypted_fields[]."""
    erd = _read_json(DOCS / "erd_spec.json")
    from_entities: Set[str] = set()
    for ent in erd.get("entities", []):
        for f in ent.get("fields", []) or []:
            if isinstance(f, dict) and f.get("encrypted") is True:
                from_entities.add(f"{ent.get('name')}.{f.get('name')}")
    manifest = erd.get("encrypted_fields")
    assert isinstance(manifest, list), "encrypted_fields[] must exist"
    assert set(manifest) == from_entities, "encrypted_fields[] must equal set of encrypted fields"


# 7.1.26 — Constraint/Index Definitions Live With Schema, Not Code
def test_constraints_and_indexes_live_in_migrations_not_code() -> None:
    """Verifies 7.1.26 — constraints/indexes defined in migrations; none in application code."""
    # Presence in SQL files
    for fname in ("001_init.sql", "002_constraints.sql", "003_indexes.sql"):
        path = MIGRATIONS / fname
        assert path.exists(), f"{path} must exist"
        sql = _read_text(path)
        assert re.search(r"\b(CREATE\s+TABLE|CREATE\s+INDEX|ALTER\s+TABLE|CONSTRAINT)\b", sql, re.IGNORECASE), (
            f"DDL tokens should be present in {fname}"
        )
    # Absence in application source code
    offenders = _ddl_tokens_present_outside_migrations()
    assert not offenders, f"DDL tokens must not appear outside migrations: {offenders}"


# 7.1.27 — Placeholder Uniqueness Encoded as a Constraint
def test_placeholder_uniqueness_enforced_via_partial_unique_on_questions() -> None:
    """Verifies 7.1.27 — partial unique on QuestionnaireQuestion(placeholder_code) non-null only."""
    erd = _read_json(DOCS / "erd_spec.json")
    qq = next((e for e in erd.get("entities", []) if e.get("name") == "QuestionnaireQuestion"), None)
    assert qq is not None, "ERD must include entity QuestionnaireQuestion"
    uniqs = qq.get("unique") or []
    assert any(
        u.get("columns") == ["placeholder_code"] and (u.get("where") or "").lower().strip() in {"placeholder_code is not null", "placeholder_code!=null"}
        for u in uniqs if isinstance(u, dict)
    ), "ERD must define partial unique on QuestionnaireQuestion(placeholder_code) where placeholder_code IS NOT NULL"

    sql = _read_text(MIGRATIONS / "002_constraints.sql")
    assert re.search(r"CREATE\s+UNIQUE\s+INDEX[\s\S]*ON\s+questionnaire_question\s*\(\s*placeholder_code\s*\)\s*WHERE\s+placeholder_code\s+IS\s+NOT\s+NULL",
                    sql, re.IGNORECASE), "002_constraints.sql must contain partial unique for placeholder_code"


# 7.1.28 — One-Response-Per-Question-Per-Submission Encoded as a Constraint
def test_one_response_per_question_per_submission_enforced() -> None:
    """Verifies 7.1.28 — composite unique (response_set_id, question_id) exists in ERD and SQL."""
    erd = _read_json(DOCS / "erd_spec.json")
    resp = next((e for e in erd.get("entities", []) if e.get("name") == "Response"), None)
    assert resp is not None, "ERD must include entity Response"
    uniqs = resp.get("unique") or []
    assert any(u.get("columns") == ["response_set_id", "question_id"] for u in uniqs if isinstance(u, dict)), (
        "ERD must define composite unique on Response(response_set_id, question_id)"
    )
    sql = _read_text(MIGRATIONS / "002_constraints.sql")
    assert re.search(r"UNIQUE\s*\(\s*response_set_id\s*,\s*question_id\s*\)", sql, re.IGNORECASE), (
        "002_constraints.sql must contain UNIQUE(response_set_id, question_id)"
    )


# 7.1.29 — Deterministic Export Parity With ERD
def test_erd_parity_exports_correspond_to_erd_spec() -> None:
    """Verifies 7.1.29 — Mermaid and CSV mirror ERD entities and relationships only."""
    erd = _read_json(DOCS / "erd_spec.json")
    mermaid = _read_text(DOCS / "erd_mermaid.md")
    rows = _read_csv_rows(DOCS / "erd_relationships.csv")
    # Assume CSV header: source,target or similar; detect columns by names
    header = [h.strip().lower() for h in rows[0]] if rows else []
    assert rows and header, "relationships CSV must be non-empty with header"
    # heuristics for columns
    try:
        src_idx = header.index("source")
        dst_idx = header.index("target")
    except ValueError:
        # fallback to first two columns
        src_idx, dst_idx = 0, 1

    csv_entities: Set[str] = set()
    csv_relationships: Set[Tuple[str, str]] = set()
    for r in rows[1:]:
        if len(r) <= max(src_idx, dst_idx):
            continue
        s, t = r[src_idx].strip(), r[dst_idx].strip()
        if s and t:
            csv_relationships.add((s, t))
            csv_entities.update({s, t})

    erd_entities = {e.get("name") for e in erd.get("entities", []) if isinstance(e, dict)}

    # Mermaid edges like: A --> B ; or A -- FK --> B; collect pairs
    mermaid_edges = set()
    for line in mermaid.splitlines():
        m = re.search(r"(\w+)\s*[-.]{2,}>\s*(\w+)", line)
        if m:
            mermaid_edges.add((m.group(1), m.group(2)))

    # Every ERD entity appears in Mermaid; CSV is only required for entities participating in relationships
    mermaid_nodes = set(re.findall(r"\bclass\s+(\w+)|\btable\s+(\w+)", mermaid))
    mermaid_nodes = {a or b for a, b in mermaid_nodes}
    assert erd_entities.issubset(mermaid_nodes), "All ERD entities must appear in Mermaid"

    # ERD relationships (from ERD FKs) appear in exports
    erd_relationships = set()
    for ent in erd.get("entities", []):
        for fk in ent.get("foreign_keys", []) or []:
            ref = fk.get("references") or {}
            tgt = ref.get("entity")
            if ent.get("name") and tgt:
                erd_relationships.add((ent["name"], tgt))

    # Only entities that participate in at least one relationship must appear in CSV
    participating_entities: Set[str] = set()
    for s, t in erd_relationships:
        participating_entities.add(s)
        participating_entities.add(t)
    assert participating_entities.issubset(csv_entities), (
        "All ERD entities with relationships must appear in relationships CSV"
    )

    assert erd_relationships.issubset(csv_relationships), "All ERD FKs must appear as CSV rows"
    assert erd_relationships.issubset(mermaid_edges), "All ERD FKs must appear as Mermaid edges"

    # No extras beyond ERD
    assert csv_relationships.issubset(erd_relationships), "CSV must not contain relationships not in ERD"
    assert mermaid_edges.issubset(erd_relationships), "Mermaid must not contain relationships not in ERD"
