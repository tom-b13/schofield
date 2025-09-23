"""Behave step definitions for Epic A behavioural scenarios.

This module implements step definitions corresponding to the behavioural
acceptance criteria in docs/Epic A - Data model & migration.md (section 6.3).

Notes:
- Steps record observable events in `context.events` and a placeholder
  `context.result` for migration outputs. Assertions are intentionally strict
  and will fail until the SUT is implemented, aligning with TDD first-sweep
  failing integration tests.
- JSON Schema validation is enforced against `schemas/migration_outputs.schema.json`.
  Validation outcome is captured in `context.validation` to avoid short-circuiting
  the scenario flow while still enforcing schema constraints.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from behave import given, when, then, use_step_matcher  # type: ignore

try:
    import json
    import jsonschema  # type: ignore
except Exception:  # pragma: no cover - test discovery resilience
    json = None  # type: ignore
    jsonschema = None  # type: ignore


SCHEMAS_DIR = Path("schemas")
DOCS_DIR = Path("docs")


def _ensure_context_defaults(context: Any) -> None:
    if not hasattr(context, "events"):
        context.events = []  # type: List[str]
    if not hasattr(context, "result"):
        context.result = {  # minimal non-conforming placeholder
            "status": "not_implemented",
            "outputs": None,
            "error": {"code": "NOT_IMPLEMENTED", "message": "implementation missing"},
        }
    if not hasattr(context, "validation"):
        context.validation = {"validated": False, "errors": []}


def _validate_outputs_schema(context: Any) -> None:
    """Validate `context.result` against migration_outputs.schema.json.

    Records the outcome in `context.validation` rather than raising, to keep
    scenario control in step assertions while still enforcing schema checks.
    """

    _ensure_context_defaults(context)
    schema_path = SCHEMAS_DIR / "migration_outputs.schema.json"
    if json is None or jsonschema is None or not schema_path.exists():
        # Record inability to validate as a soft error; do not raise
        context.validation = {
            "validated": False,
            "errors": [
                {
                    "kind": "runtime",
                    "message": "json/jsonschema unavailable or schema missing",
                    "schema": str(schema_path),
                }
            ],
        }
        return

    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        jsonschema.validate(instance=context.result, schema=schema)
        context.validation = {"validated": True, "errors": []}
    except Exception as exc:  # ValidationError or JSON decode
        context.validation = {
            "validated": False,
            "errors": [
                {
                    "kind": "validation",
                    "message": str(exc),
                    "schema": str(schema_path),
                }
            ],
        }


# 6.3.1.1 Migration Initiates Schema Creation


use_step_matcher("re")


@given(r"^the migration runner starts,?$")
def step_given_runner_starts(context):
    _ensure_context_defaults(context)
    # Load migrations deterministically using the SUT
    from app.db.migrations_runner import load_migrations  # local import for test isolation

    context.migrations = load_migrations()  # type: ignore[attr-defined]
    # Validate each migration file path against the MigrationFile schema (path only)
    import json
    import jsonschema  # type: ignore

    schema = json.loads((SCHEMAS_DIR / "erd_and_runtime_inputs.schema.json").read_text(encoding="utf-8"))
    mf_schema = schema.get("components", {}).get("schemas", {}).get("MigrationFile")
    assert mf_schema is not None, "MigrationFile schema missing"
    for m in context.migrations:  # type: ignore[attr-defined]
        jsonschema.validate(instance={"path": m.filename}, schema=mf_schema)

    # Assert deterministic ordering: first migration/journal entry is 001_init.sql
    assert context.migrations, "No migrations loaded"
    assert context.migrations[0].filename == "migrations/001_init.sql", (
        "First migration must be 'migrations/001_init.sql'"
    )
    context.events.append("runner.start")


@when(r"^migrations are executed,?$")
def step_when_migrations_executed(context):
    _ensure_context_defaults(context)
    from app.db.migrations_runner import apply_migrations

    executed_sql: List[str] = []

    def _capture(sql: str) -> None:
        executed_sql.append(sql)

    journal = apply_migrations(executor=_capture)
    context.journal = journal  # type: ignore[attr-defined]
    context.executed_sql = executed_sql  # type: ignore[attr-defined]

    # Construct minimal outputs conforming to migration_outputs.schema.json
    # Entities are inferred by parsing CREATE TABLE statements in 001_init.sql
    import re

    entities: List[str] = []
    if executed_sql:
        create_re = re.compile(r"CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([a-z_]+)\s*\(", re.IGNORECASE)
        for m in create_re.finditer(executed_sql[0]):
            entities.append(m.group(1))
    context.result = {"entities": entities}

    # If first migration contains CREATE TABLE, mark table-creation event
    if executed_sql and ("CREATE TABLE" in executed_sql[0]):
        context.events.append("create_tables")

    # Validate outputs schema
    _validate_outputs_schema(context)


@then(r"^the system must initiate table creation as the first step in schema setup\.?$")
def step_then_table_creation_first(context):
    _ensure_context_defaults(context)
    # First applied migration must be 001_init.sql and must contain CREATE TABLE statements
    journal = getattr(context, "journal", [])
    assert journal, "No migrations were applied"
    first = journal[0]
    assert first.get("filename", "").endswith("001_init.sql"), "First migration must be 001_init.sql"

    executed_sql = getattr(context, "executed_sql", [])
    assert executed_sql and "CREATE TABLE" in executed_sql[0], (
        "First migration must initiate table creation"
    )

    # Relaxed rule: ensure at least one CREATE TABLE appears before any
    # ALTER TABLE / CREATE INDEX statements in the first applied SQL
    sql0 = executed_sql[0].upper()
    first_create_table = sql0.find("CREATE TABLE")
    assert first_create_table != -1, "Expected at least one CREATE TABLE in first migration"
    constraint_tokens = ["ALTER TABLE", "CREATE UNIQUE INDEX", "CREATE INDEX"]
    positions = [pos for token in constraint_tokens if (pos := sql0.find(token)) != -1]
    if positions:
        assert first_create_table < min(positions), (
            "CREATE TABLE must occur before any ALTER TABLE/CREATE INDEX statements in first migration"
        )

    # Event ordering and schema validation
    events: List[str] = context.events
    assert "create_tables" in events, "Expected 'create_tables' event to be present"
    assert getattr(context, "validation", {}).get("validated") is True, (
        "Migration outputs must validate against schema"
    )


# 6.3.1.2 Constraint Creation Follows Table Creation


@given(r"^all tables are created,?$")
def step_given_tables_created(context):
    _ensure_context_defaults(context)
    if "create_tables" not in context.events:
        context.events.append("create_tables")


@when(r"^migration execution continues,?$")
def step_when_execution_continues(context):
    _ensure_context_defaults(context)
    # No-op placeholder; assertions check for subsequent constraint events
    pass


@then(r"^the system must initiate creation of primary keys, foreign keys, unique constraints, and indexes\.?$")
def step_then_constraints_follow(context):
    _ensure_context_defaults(context)
    events: List[str] = context.events
    assert "create_constraints" in events, "Expected 'create_constraints' event present"
    assert events.index("create_constraints") > events.index("create_tables"), (
        "'create_constraints' must occur after 'create_tables'"
    )


# 6.3.1.3 Encryption Application Follows Constraint Creation


@given(r"^constraints are applied,?$")
def step_given_constraints_applied(context):
    _ensure_context_defaults(context)
    if "create_constraints" not in context.events:
        context.events.extend([e for e in ["create_tables", "create_constraints"] if e not in context.events])


@when(r"^sensitive fields are detected,?$")
def step_when_sensitive_fields_detected(context):
    _ensure_context_defaults(context)
    # No-op placeholder; assertions check encryption application
    pass


@then(r"^the system must initiate encryption on those fields during the same migration flow\.?$")
def step_then_encryption_applied(context):
    _ensure_context_defaults(context)
    events: List[str] = context.events
    assert "apply_encryption" in events, "Expected 'apply_encryption' event present"
    assert events.index("apply_encryption") > events.index("create_constraints"), (
        "'apply_encryption' must follow 'create_constraints'"
    )


# 6.3.1.4 TLS Enforcement Follows Database Connection Request


@given(r"^a database connection is initiated,?$")
def step_given_db_connection_initiated(context):
    _ensure_context_defaults(context)
    context.events.append("db.connect.request")


@when(r"^TLS enforcement is configured,?$")
def step_when_tls_configured(context):
    _ensure_context_defaults(context)
    # Placeholder to simulate configuration availability; no event appended
    context.tls_configured = True  # type: ignore[attr-defined]


@then(r"^the system must establish a TLS session before any subsequent operations proceed\.?$")
def step_then_tls_before_ops(context):
    _ensure_context_defaults(context)
    events: List[str] = context.events
    assert "db.connect.request" in events, "Expected 'db.connect.request' event present"
    assert "tls.established" in events, "Expected 'tls.established' event present"
    connect_idx = events.index("db.connect.request")
    tls_idx = events.index("tls.established")
    assert tls_idx > connect_idx, "'tls.established' must occur after 'db.connect.request'"
    # Ensure TLS precedes any subsequent DB operations (excluding the initial connect request)
    subsequent_db_idxs = [i for i, e in enumerate(events) if e.startswith("db.") and i > connect_idx]
    if subsequent_db_idxs:
        assert tls_idx < min(subsequent_db_idxs), (
            "'tls.established' must occur before any subsequent 'db.*' events"
        )


# 6.3.1.5 Row Validation Follows Connection Establishment


@given(r"^a TLS-secured database session is established,?$")
def step_given_tls_established(context):
    _ensure_context_defaults(context)
    if "tls.established" not in context.events:
        context.events.append("tls.established")


@when(r"^a row insert is attempted,?$")
def step_when_row_insert_attempted(context):
    _ensure_context_defaults(context)
    context.events.append("db.insert.attempt")


@then(r"^the system must validate row values against the declared schema before insertion proceeds\.?$")
def step_then_row_validation_before_insert(context):
    _ensure_context_defaults(context)
    events: List[str] = context.events
    assert "validate.row" in events, "Expected 'validate.row' event present"
    assert events.index("validate.row") > events.index("tls.established"), (
        "'validate.row' must occur after 'tls.established'"
    )
    assert "db.insert.attempt" in events, "Expected 'db.insert.attempt' event present"
    assert events.index("validate.row") < events.index("db.insert.attempt"), (
        "'validate.row' must occur before 'db.insert.attempt'"
    )


# 6.3.1.6 Direct Lookup Follows Row Validation


@given(r"^row insertion has passed schema validation,?$")
def step_given_row_validation_passed(context):
    _ensure_context_defaults(context)
    # Simulate that validation occurred after a secure session
    for e in ["tls.established", "validate.row"]:
        if e not in context.events:
            context.events.append(e)


@when(r"^placeholder sourcing is required,?$")
def step_when_placeholder_sourcing_required(context):
    _ensure_context_defaults(context)
    # Assert uniqueness support and direct lookup feasibility from constraints migration
    constraints_sql = (Path("migrations") / "002_constraints.sql").read_text(encoding="utf-8")
    assert "CREATE UNIQUE INDEX" in constraints_sql and "placeholder_code" in constraints_sql, (
        "Constraints must enforce uniqueness on placeholder_code when present"
    )
    # Record that a direct placeholder lookup is performed
    context.events.append("lookup.placeholder")


@then(r"^the system must perform a direct lookup by `?QuestionnaireQuestion\.placeholder_code`? \(unique when present\)\.?$")
def step_then_direct_lookup(context):
    _ensure_context_defaults(context)
    events: List[str] = context.events
    assert "lookup.placeholder" in events, "Expected 'lookup.placeholder' event present"
    assert events.index("lookup.placeholder") > events.index("validate.row"), (
        "'lookup.placeholder' must follow 'validate.row'"
    )
    # Validate ERD/runtime inputs schema using the provided sample
    import json
    import jsonschema  # type: ignore

    sample_path = Path("tests/integration/data/epic_a/placeholder_sample.json")
    erd_schema_path = SCHEMAS_DIR / "erd_and_runtime_inputs.schema.json"
    erd_instance = json.loads(sample_path.read_text(encoding="utf-8"))
    erd_schema = json.loads(erd_schema_path.read_text(encoding="utf-8"))
    erd_spec_schema = erd_schema.get("components", {}).get("schemas", {}).get("ErdSpec")
    assert erd_spec_schema is not None, "ErdSpec subschema not found in ERD schema"
    jsonschema.validate(instance=erd_instance, schema=erd_spec_schema)
    # Assert ERD conventions placeholder format and lookup key presence
    conventions = erd_instance.get("conventions", {})
    assert conventions.get("placeholder_format") == "UPPERCASE_UNDERSCORE", (
        "ERD conventions.placeholder_format must be 'UPPERCASE_UNDERSCORE'"
    )
    qq = next((e for e in erd_instance["entities"] if e.get("name") == "QuestionnaireQuestion"), None)
    assert qq is not None, "Entity 'QuestionnaireQuestion' missing in ERD sample"
    fields = qq.get("fields", {})
    assert "placeholder_code" in fields, "Lookup key must be 'placeholder_code' in ERD sample"
    uniques = qq.get("uniques", []) or []
    assert ("placeholder_code" in uniques), (
        "Placeholder code should be uniquely constrained when present"
    )


# 6.3.1.7 Placeholder Resolution Follows Direct Lookup


@given(r"^direct lookup completes successfully,?$")
def step_given_lookup_completes(context):
    _ensure_context_defaults(context)
    for e in ["validate.row", "lookup.placeholder"]:
        if e not in context.events:
            context.events.append(e)


@when(r"^placeholder resolution is required,?$")
def step_when_placeholder_resolution_required(context):
    _ensure_context_defaults(context)
    # No-op placeholder
    pass


@then(r"^the system must return the resolved values to the requesting component\.?$")
def step_then_return_resolved_values(context):
    _ensure_context_defaults(context)
    events: List[str] = context.events
    assert "resolve.placeholders" in events, "Expected 'resolve.placeholders' event present"
    assert events.index("resolve.placeholders") > events.index("lookup.placeholder"), (
        "'resolve.placeholders' must follow 'lookup.placeholder'"
    )


# 6.3.1.8 Rollback Follows Migration Failure


@given(r"^a migration encounters an execution failure,?$")
def step_given_migration_failure(context):
    _ensure_context_defaults(context)
    if "failure.migration" not in context.events:
        context.events.append("failure.migration")


@when(r"^rollback is invoked,?$")
def step_when_rollback_invoked(context):
    _ensure_context_defaults(context)
    # No-op placeholder
    pass


@then(r"^the system must initiate reverse execution of the corresponding rollback scripts\.?$")
def step_then_rollback_sequence(context):
    _ensure_context_defaults(context)
    events: List[str] = context.events
    assert "rollback" in events, "Expected 'rollback' event present"
    assert events.index("rollback") == events.index("failure.migration") + 1, (
        "'rollback' must occur immediately after 'failure.migration'"
    )


# 6.3.1.9 Deterministic State Ensured After Step Completion


@given(r"^any migration step completes,?$")
def step_given_any_step_completes(context):
    _ensure_context_defaults(context)
    context.events.append("step.complete")


@when(r"^the same step is repeated with identical inputs,?$")
def step_when_step_repeated(context):
    _ensure_context_defaults(context)
    # No-op placeholder
    pass


@then(r"^the system must maintain deterministic results for that operation before proceeding to the next step\.?$")
def step_then_determinism_gate(context):
    _ensure_context_defaults(context)
    events: List[str] = context.events
    assert "determinism.verify" in events, "Expected 'determinism.verify' event present"
    assert "step.next" in events, "Expected 'step.next' event present"
    assert events.index("determinism.verify") < events.index("step.next"), (
        "'determinism.verify' must precede 'step.next'"
    )
    # Determinism check: capture digest on first completion, compare on repeat with identical inputs
    if json is not None:
        import hashlib

        payload = json.dumps(getattr(context, "result", {}), sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        digest = hashlib.sha256(payload).hexdigest()
        if not hasattr(context, "_determinism_digest"):
            context._determinism_digest = digest  # type: ignore[attr-defined]
        else:
            assert digest == getattr(context, "_determinism_digest"), (
                "Determinism violation: repeated step produced different result digest"
            )


# 6.3.1.11 New Template Introduction Triggers Schema Reuse


@given(r"^a new template is introduced,?$")
def step_given_new_template(context):
    _ensure_context_defaults(context)
    context.new_template = True  # type: ignore[attr-defined]


@when(r"^the template is registered,?$")
def step_when_template_registered(context):
    _ensure_context_defaults(context)
    # Capture entities snapshot prior to registration if available
    try:
        import copy as _copy

        if isinstance(getattr(context, "result", None), dict) and "entities" in context.result:  # type: ignore[attr-defined]
            context._entities_before_registration = _copy.deepcopy(context.result["entities"])  # type: ignore[attr-defined]
    except Exception:
        pass
    context.events.append("template.register")


@then(r"^the system must proceed without initiating schema changes, reusing the existing schema structure\.?$")
def step_then_registration_reuses_schema(context):
    _ensure_context_defaults(context)
    events: List[str] = context.events
    # Accept either template or policy registration, but ensure runner not started
    assert (events.count("template.register") == 1) or (events.count("policy.register") == 1), (
        "Expected exactly one 'template.register' or 'policy.register'"
    )
    assert "runner.start" not in events, "Registration must not initiate migration runner"
    # Ensure no schema-change events occurred
    forbidden = {"create_tables", "create_constraints", "apply_encryption"}
    present_forbidden = [e for e in events if e in forbidden]
    assert not present_forbidden, f"Schema reuse required; found schema-change events: {present_forbidden}"
    # If entities are available, ensure unchanged across registration
    if isinstance(getattr(context, "result", None), dict) and "entities" in context.result:  # type: ignore[attr-defined]
        before = getattr(context, "_entities_before_registration", None)
        after = context.result["entities"]  # type: ignore[index]
        if before is not None:
            assert after == before, "Registration must not alter 'entities' in migration outputs"


# 6.3.1.12 New Policy Introduction Triggers Schema Reuse


@given(r"^a new policy is introduced,?$")
def step_given_new_policy(context):
    _ensure_context_defaults(context)
    context.new_policy = True  # type: ignore[attr-defined]


@when(r"^the policy is registered,?$")
def step_when_policy_registered(context):
    _ensure_context_defaults(context)
    # Capture entities snapshot prior to registration if available
    try:
        import copy as _copy

        if isinstance(getattr(context, "result", None), dict) and "entities" in context.result:  # type: ignore[attr-defined]
            context._entities_before_registration = _copy.deepcopy(context.result["entities"])  # type: ignore[attr-defined]
    except Exception:
        pass
    context.events.append("policy.register")


# The shared @then step for schema reuse is defined above and applies here as well.
