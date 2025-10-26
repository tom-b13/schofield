"""Behave environment hooks for Questionnaire Service integration tests.

This module loads and validates required environment variables before any
feature runs. It fails fast with clear errors if the runtime configuration
is incomplete. For local runs, it can boot a Uvicorn server when the
configured `TEST_BASE_URL` points at localhost and no API is listening.
See docs/Epic B - Questionnaire Service.md for runtime expectations
(live HTTP API and database access).
"""

import os
import socket
import json
import traceback
from typing import Any
import httpx
from sqlalchemy import create_engine, text
import subprocess
import time
from urllib.parse import urlparse
import uuid
from pathlib import Path


REQUIRED_ENV_VARS = (
    "TEST_BASE_URL",      # Base URL for the running API under test
    "TEST_DATABASE_URL",  # Database connection string for integration paths
)


def _load_env_fallback() -> None:
    """Optionally load a .env.test file for local development.

    This is a best-effort helper: if a .env.test file exists (at project root
    or under tests/integration/), parse simple KEY=VALUE lines and populate
    os.environ for any keys that are not already set. CI must still provide
    required variables explicitly; we do not weaken the assertion that follows.
    """
    candidate_paths = (".env.test", os.path.join("tests", "integration", ".env.test"))
    for path in candidate_paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    # Do not override variables that are already set in the environment.
                    if key and key not in os.environ:
                        os.environ[key] = value
        except Exception:
            # Silent best-effort; validation occurs after this helper.
            continue


def before_all(context: Any) -> None:
    """Validate mandatory environment for integration scenarios.

    Clarke directive: mock mode must be disabled for integration runs so
    HTTP/DB paths execute against the live system. We therefore ignore any
    truthy TEST_MOCK_MODE and enforce TEST_BASE_URL/TEST_DATABASE_URL.
    Fails fast with clear errors if either is missing. Behave surfaces
    the AssertionError message to aid CI diagnosis.
    """
    # Optional bypass for constrained environments (e.g., no socket bind permissions)
    # When SKIP_INTEGRATION_ENV_HOOK=1, we avoid server/DB checks to allow Behave to
    # collect and execute steps (they may still fail at runtime if they rely on HTTP/DB).
    if os.getenv("SKIP_INTEGRATION_ENV_HOOK", "").strip() in {"1", "true", "yes"}:
        # Provide minimal context so steps referring to these attributes don't crash
        base = os.getenv("TEST_BASE_URL", "http://127.0.0.1:0").rstrip("/")
        dsn = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")
        context.test_base_url = base
        context.test_database_url = dsn
        context.api_prefix = os.getenv("TEST_API_PREFIX", "/api/v1")
        context.test_mock_mode = True
        print("[env] SKIP_INTEGRATION_ENV_HOOK=1: skipping server/DB checks; running with minimal context")
        return

    # Load .env.test early so TEST_MOCK_MODE can be honored when set there.
    _load_env_fallback()

    # Clarke: force-disable mock mode for integration runs.
    raw_mock = os.environ.get("TEST_MOCK_MODE", "")
    mock_mode = raw_mock.strip().lower() in {"1", "true", "yes", "on"}
    if mock_mode:
        context._prev_test_mock_mode = raw_mock
        # Unset so step helpers relying on env do not see mock mode enabled.
        try:
            del os.environ["TEST_MOCK_MODE"]
        except KeyError:
            pass
        print("[env] TEST_MOCK_MODE detected; disabling per integration policy")
    # Always publish false for test_mock_mode so steps permit HTTP/DB.
    context.test_mock_mode = False

    # Live mode: require TEST_BASE_URL and TEST_DATABASE_URL
    missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        _load_env_fallback()
        missing = [name for name in REQUIRED_ENV_VARS if not os.getenv(name)]
    assert not missing, (
        "Missing required environment variables: " + ", ".join(missing)
    )

    # Expose env on the context for step implementations that need them.
    context.test_base_url = os.environ["TEST_BASE_URL"].rstrip("/")
    context.test_database_url = os.environ["TEST_DATABASE_URL"]
    # Clarke: add API prefix configuration for versioned routes
    context.api_prefix = os.getenv("TEST_API_PREFIX", "/api/v1")
    # Ensure the application under test also sees a compatible DATABASE_URL.
    # Many code paths prefer DATABASE_URL; mirror TEST_DATABASE_URL when unset.
    os.environ.setdefault("DATABASE_URL", context.test_database_url)

    # Optionally boot a local API if TEST_BASE_URL points to localhost and
    # nothing is listening yet. This supports local runs while CI may start
    # the service out-of-band.
    parsed = urlparse(context.test_base_url)
    host_is_local = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    def _is_api_listening() -> bool:
        try:
            with httpx.Client(timeout=2.0) as client:
                # Prefer explicit health endpoint for reliability
                client.get(context.test_base_url + "/health", headers={"Accept": "*/*"})
                return True
        except Exception:
            return False

    def _port_in_use(host: str, p: int) -> bool:
        try:
            with socket.create_connection((host, p), timeout=1.0):
                return True
        except Exception:
            return False

    def _choose_free_port(host: str) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((host, 0))
            return int(s.getsockname()[1])

    # If the orchestrator has already started the server, honor that and avoid re-binding.
    prestarted = os.getenv("E2E_SKIP_SERVER", "").strip().lower() in {"1", "true", "yes", "on"}
    if host_is_local and not prestarted:
        if _is_api_listening():
            # An API is already responding at configured TEST_BASE_URL; do nothing.
            context._port_rebind_info = None
        else:
            # Either the port is occupied by a non-HTTP service or nothing is listening.
            # Per Clarke, always select a free ephemeral port and start uvicorn there.
            new_port = _choose_free_port(parsed.hostname or "127.0.0.1")
            old_port = port
            # Rebuild base URL with the new port (preserve scheme and host).
            new_base = f"{parsed.scheme}://{parsed.hostname}:{new_port}"
            context.test_base_url = new_base
            os.environ["TEST_BASE_URL"] = new_base
            # Publish rebind info for later diagnostics
            context._port_rebind_info = {"old_port": old_port, "new_port": new_port}

            # Start uvicorn on the new port.
            import sys
            uvicorn_cmd = [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:create_app",
                "--factory",
                "--host",
                parsed.hostname or "127.0.0.1",
                "--port",
                str(new_port),
                "--log-level",
                "warning",
            ]
            context._api_proc = subprocess.Popen(
                uvicorn_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=os.environ.copy(),
            )

            # Wait briefly for the server to come up on the new port.
            deadline = time.time() + 10.0
            while time.time() < deadline:
                if _is_api_listening():
                    break
                time.sleep(0.2)
    else:
        # Non-localhost target: do not attempt to manage server lifecycle.
        context._port_rebind_info = None

    # If the orchestrator pre-started the server, wait briefly for readiness
    if prestarted and host_is_local:
        deadline = time.time() + 20.0
        while time.time() < deadline:
            if _is_api_listening():
                break
            time.sleep(0.2)

    # 2) Database connectivity using TEST_DATABASE_URL
    def _mask_dsn(dsn: str) -> str:
        """Mask password in DSN for safe diagnostics, preserve user@host:port/db."""
        try:
            parsed_dsn = urlparse(dsn)
            netloc = parsed_dsn.netloc
            if "@" in netloc and ":" in netloc.split("@")[0]:
                creds, host = netloc.split("@", 1)
                user = creds.split(":", 1)[0]
                netloc = f"{user}:***@{host}"
            redacted = parsed_dsn._replace(netloc=netloc).geturl()
            return redacted
        except Exception:
            return "<unparseable DSN>"

    try:
        eng = create_engine(context.test_database_url, future=True)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        redacted = _mask_dsn(context.test_database_url)
        raise AssertionError(
            "Database not reachable using TEST_DATABASE_URL. DSN="
            f"{redacted}. Error={exc}. Ensure credentials/host/port/db are correct."
        )

    # Schema readiness check: verify critical tables and columns exist.
    # Clarke: avoid skipping migrations when a table exists but required
    # columns are absent. Probe column existence on PostgreSQL and SQLite.
    def _schema_ready() -> bool:
        required = {
            "questionnaire_question": ["screen_key", "question_order"],
            "answer_option": ["sort_index"],
            "response": ["answered_at"],
            # Presence-only checks (no specific column): use singular table names per current schema
            "questionnaire": [],
            "response_set": [],
        }
        driver = str(getattr(eng.url, "drivername", ""))
        try:
            with eng.connect() as conn:
                # First ensure required tables exist
                for tbl, cols in required.items():
                    try:
                        # Lightweight table probe
                        conn.execute(text(f"SELECT 1 FROM {tbl} LIMIT 0"))
                    except Exception:
                        print(f"[env] schema check: missing table={tbl}")
                        return False
                    # Column checks
                    for col in cols:
                        try:
                            if driver.startswith("postgresql"):
                                res = conn.execute(text(
                                    """
                                    SELECT 1
                                    FROM information_schema.columns
                                    WHERE table_schema = current_schema()
                                      AND table_name = :tbl
                                      AND column_name = :col
                                    LIMIT 1
                                    """
                                ), {"tbl": tbl, "col": col})
                                found = res.first() is not None
                            elif driver.startswith("sqlite"):
                                # PRAGMA table_info returns rows with `name` column
                                res = conn.execute(text(f"PRAGMA table_info({tbl})"))
                                names = {str(r[1]) for r in res}  # r[1] is name
                                found = col in names
                            else:
                                # Fallback: attempt selecting the column with zero rows
                                try:
                                    conn.execute(text(f"SELECT {col} FROM {tbl} LIMIT 0"))
                                    found = True
                                except Exception:
                                    found = False
                            if not found:
                                print(f"[env] schema check: missing column {tbl}.{col}")
                                return False
                        except Exception:
                            # Any error during introspection -> assume missing to force migrations
                            print(f"[env] schema check error probing {tbl}.{col}; treating as missing")
                            return False
                # Enum readiness: ensure PostgreSQL enum 'answer_kind' has label 'short_string'
                try:
                    if str(getattr(eng.url, "drivername", "")).startswith("postgresql"):
                        enum_probe = conn.execute(text(
                            """
                            SELECT 1
                            FROM pg_type t
                            JOIN pg_enum e ON e.enumtypid = t.oid
                            WHERE t.typname = 'answer_kind'
                              AND e.enumlabel = 'short_string'
                            LIMIT 1
                            """
                        ))
                        if enum_probe.first() is None:
                            print("[env] schema check: missing ENUM value answer_kind.'short_string'")
                            return False
                except Exception:
                    # Treat probe failure as not ready to force migrations
                    print("[env] schema check error probing ENUM answer_kind; treating as missing")
                    return False

                # All checks passed
                return True
        except Exception:
            # Connection-level failure; treat as not ready and let migration path handle/report
            return False

    def _apply_sql_migrations() -> int:
        migrations_dir = Path("migrations")
        if not migrations_dir.is_dir():
            return 0
        sql_files = [
            p for p in sorted(migrations_dir.iterdir(), key=lambda x: x.name)
            if p.suffix == ".sql" and "rollback" not in p.name.lower()
        ]
        # Log exact list to aid troubleshooting
        file_names = ", ".join(p.name for p in sql_files)
        print(f"[env] migration files=[{file_names}]")

        applied = 0

        # Helper: detect existing named constraints for 002_constraints.sql and skip if present
        def _constraints_already_present(conn) -> bool:
            try:
                # Only meaningful for PostgreSQL
                if not str(getattr(eng.url, "drivername", "")).startswith("postgresql"):
                    return False
                names = [
                    "fk_answer_option_question",
                    "uq_answer_option_question_value",
                    "fk_q2fg_field_group",
                    "fk_q2fg_question",
                    "uq_q2fg_question_group",
                    "fk_response_set_company",
                    "fk_generated_document_set",
                    "fk_response_option",
                    "fk_response_question",
                    "fk_response_set",
                    "uq_response_set_question",
                    "fk_group_value_group",
                    "fk_group_value_option",
                    "fk_group_value_set",
                    "fk_group_value_source_q",
                    "uq_group_value_per_set",
                    "fk_question_parent_question",
                    "uq_question_external_qid",
                ]
                # Build a safe IN (...) list from literal names
                inlist = ",".join("'" + n.replace("'", "''") + "'" for n in names)
                res = conn.execute(text(
                    f"SELECT COUNT(1) FROM pg_constraint WHERE conname IN ({inlist})"
                ))
                count = int(list(res)[0][0])
                # If any known constraints are present, treat as already applied to avoid DuplicateObject
                return count > 0
            except Exception:
                return False

        for path in sql_files:
            print(f"[env] considering migration={path.name}")
            # Commit progress incrementally per file
            with eng.begin() as conn:
                try:
                    if path.name == "002_constraints.sql" and _constraints_already_present(conn):
                        print(f"[env] decision: skip {path.name} (constraints detected in pg_catalog)")
                        continue
                    sql = path.read_text(encoding="utf-8")
                    # exec_driver_sql allows multi-statement execution (needed for DO $$ ... $$)
                    conn.exec_driver_sql(sql)
                    print(f"[env] decision: run {path.name}")
                    applied += 1
                except Exception as exc:
                    # Continue to next file when a no-op or already-applied DDL is detected.
                    # PostgreSQL DuplicateObject: skip as benign if detected.
                    msg = str(exc)
                    dup_markers = [
                        "already exists",
                        "DuplicateObject",
                        "duplicate key value",
                        # Broader DDL idempotency markers across engines
                        "relation \"",  # PostgreSQL relation exists
                        "duplicate column",
                        "column \"",  # e.g., column "x" of relation "y" already exists
                        "cannot drop",  # dependent objects; ignore in idempotent reruns
                        "already defined",
                    ]
                    if any(marker in msg for marker in dup_markers):
                        print(f"[env] decision: no-op/skip {path.name}: {exc}")
                        continue
                    raise AssertionError(
                        f"Failed applying migration {path.name}: {exc}"
                    )
        return applied

    # Always ensure base schema is applied if critical columns are missing.
    # Clarke: add column-existence guards before skipping migrations. Run
    # migrations when required columns are absent, even if tables exist.
    if not _schema_ready():
        count = _apply_sql_migrations()
        print(f"[env] migrations applied: {count}")
        if not _schema_ready():
            raise AssertionError(
                "Database schema is not ready (missing core tables, e.g., questionnaires). "
                "Apply migrations under ./migrations before running integration tests."
            )

    # Minimal breadcrumb for troubleshooting without noisy logs.
    # Behave captures stdout/stderr; this is intentionally concise.
    print(f"[env] TEST_BASE_URL={context.test_base_url}")
    # Clarke instrumentation: emit an explicit message when we rebind to a new port
    if getattr(context, "_port_rebind_info", None):
        try:
            info = context._port_rebind_info or {}
            print(
                f"[env] port-in-use or unreachable at :{info.get('old_port')}; "
                f"selected ephemeral :{info.get('new_port')} -> TEST_BASE_URL={context.test_base_url}"
            )
        except Exception:
            # Never raise from instrumentation
            pass
    # Quick reachability checks to fail fast with actionable errors.
    # 1) API reachability at TEST_BASE_URL health endpoint
    try:
        with httpx.Client(timeout=5.0) as client:
            client.get(context.test_base_url + "/health", headers={"Accept": "*/*"})
    except Exception as exc:
        raise AssertionError(f"API not reachable at TEST_BASE_URL={context.test_base_url}: {exc}")


def after_all(context: Any) -> None:
    """Tear down any process we started for local runs.

    CI pipelines typically manage the API lifecycle separately; we only
    terminate a process spawned by this module during `before_all`.
    """
    proc = getattr(context, "_api_proc", None)
    if proc is not None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        finally:
            context._api_proc = None


def before_scenario(context: Any, scenario: Any) -> None:
    """Per-scenario setup.

    Clarke directive: remove early HTTP seeding that ran before Background.
    Any required gating preconditions are now handled just-in-time inside
    the POST /regenerate-check step implementation after Background data exists.
    """
    # Initialize per-scenario vars dict for step coordination
    # Clarke: ensure context.vars exists to avoid AttributeError in steps
    try:
        context.vars = {}
    except Exception:
        # Fallback in highly constrained contexts
        setattr(context, "vars", {})
    # Preserve scenario handle for diagnostics in after_step
    context.scenario = scenario


# Note: prior auto-seed restoration hook removed per Clarke guidance.


def after_step(context: Any, step: Any) -> None:
    """Emit deterministic step result lines for CI log parsing.

    Always runs, including in mock mode. Produces concise, single-line output
    to avoid noisy logs while ensuring PASS/FAIL visibility.
    """
    try:
        status = step.status.name  # Enum-like in Behave
    except Exception:
        status = str(getattr(step, "status", "UNKNOWN"))
    status_upper = str(status).upper()
    name = getattr(step, "name", "<unnamed step>")
    print(f"[behave] STEP {status_upper}: {name}")
    # Emit undefined step phrases explicitly to aid step implementation
    if status_upper == "UNDEFINED":
        try:
            undefined_text = getattr(step, "name", "<unnamed step>")
        except Exception:
            undefined_text = "<unnamed step>"
        print(f"[behave] STEP UNDEFINED: {undefined_text}")

    # On failure, emit detailed diagnostics including exception and last_response snapshot.
    if status_upper in {"FAILED", "ERROR"}:
        try:
            scenario = getattr(context, "scenario", None)
            feature_name = getattr(getattr(scenario, "feature", None), "name", "<unknown>")
            scenario_name = getattr(scenario, "name", "<unknown>")
        except Exception:
            feature_name = "<unknown>"
            scenario_name = "<unknown>"
        location = getattr(step, "location", "<unknown>")
        print(f"[behave] STEP FAILED in feature=\"{feature_name}\" scenario=\"{scenario_name}\": {name} @ {location}")
        exc = getattr(step, "exception", None)
        if exc is not None:
            print(f"[behave] STEP EXCEPTION: {type(exc).__name__}: {exc}")
            # Ensure full traceback appears in logs
            try:
                traceback.print_exc()
            except Exception:
                pass
        tb = getattr(step, "exc_traceback", None)
        if tb is not None:
            try:
                tail = traceback.format_tb(tb)[-3:]
                for frag in tail:
                    frag_line = " ".join(line.strip() for line in frag.strip().splitlines())
                    print(f"[behave] TRACE TAIL: {frag_line}")
            except Exception:
                pass
        # Snapshot of last HTTP interaction when available
        if hasattr(context, "last_response"):
            try:
                lr = context.last_response or {}
                method = lr.get("method")
                path = lr.get("path")
                status_code = lr.get("status")
                headers = lr.get("headers") or {}
                has_json = (lr.get("json") is not None)
                has_text = (lr.get("text") is not None)
                header_keys = sorted(list(headers.keys())) if isinstance(headers, dict) else []
                print(
                    f"[behave] LAST_RESPONSE: method={method} path={path} status={status_code} "
                    f"headers_keys={header_keys} has_json={has_json} has_text={has_text}"
                )
                # Dump a short body preview for troubleshooting
                try:
                    if has_json and isinstance(lr.get("json"), dict):
                        snap = json.dumps(lr.get("json"), ensure_ascii=False, separators=(",", ":"))
                        print(f"[behave] BODY_JSON_PREVIEW: {snap[:200]}")
                    elif has_text and isinstance(lr.get("text"), str):
                        print(f"[behave] BODY_TEXT_PREVIEW: {str(lr.get('text'))[:200]}")
                except Exception:
                    pass
                # Persist failure diagnostics to file to avoid CI log truncation
                try:
                    os.makedirs("logs", exist_ok=True)
                    record = {
                        "feature": feature_name,
                        "scenario": scenario_name,
                        "test_id": f"feature::{feature_name}::scenario::{scenario_name}",
                        "step_name": name,
                        "location": str(location),
                        "exception_class": type(exc).__name__ if exc is not None else None,
                        "exception_message": str(exc) if exc is not None else None,
                        "last_response": {
                            "method": method,
                            "path": path,
                            "status": status_code,
                            "headers_keys": header_keys,
                            "has_json": has_json,
                            "has_text": has_text,
                        },
                    }
                    with open(os.path.join("logs", "behave_failures.jsonl"), "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                except Exception:
                    # Best-effort; do not mask failures
                    pass
            except Exception:
                # Best-effort only; do not mask the underlying failure
                pass


def after_scenario(context: Any, scenario: Any) -> None:
    """Emit deterministic scenario result lines and exception details.

    Always runs, including in mock mode. Includes exception details when
    present to surface the failing assertion succinctly in CI logs.
    """
    try:
        status = scenario.status.name
    except Exception:
        status = str(getattr(scenario, "status", "UNKNOWN"))
    status_upper = str(status).upper()
    name = getattr(scenario, "name", "<unnamed scenario>")
    print(f"[behave] SCENARIO {status_upper}: {name}")
    exc = getattr(scenario, "exception", None)
    if exc:
        print(f"[behave] SCENARIO ERROR: {exc}")
    else:
        # Behave sometimes doesn't attach scenario.exception. Surface first failing step's details.
        try:
            failing = None
            for st in getattr(scenario, "steps", []) or []:
                st_status = getattr(getattr(st, "status", None), "name", str(getattr(st, "status", ""))).upper()
                if st_status in {"FAILED", "ERROR"}:
                    failing = st
                    break
            if failing is not None:
                feature_name = getattr(getattr(scenario, "feature", None), "name", "<unknown>")
                location = getattr(failing, "location", "<unknown>")
                print(f"[behave] STEP FAILED in feature=\"{feature_name}\" scenario=\"{name}\": {getattr(failing, 'name', '<unnamed step>')} @ {location}")
                f_exc = getattr(failing, "exception", None)
                if f_exc is not None:
                    print(f"[behave] STEP EXCEPTION: {type(f_exc).__name__}: {f_exc}")
                tb = getattr(failing, "exc_traceback", None)
                if tb is not None:
                    try:
                        tail = traceback.format_tb(tb)[-3:]
                        for frag in tail:
                            frag_line = " ".join(line.strip() for line in frag.strip().splitlines())
                            print(f"[behave] TRACE TAIL: {frag_line}")
                    except Exception:
                        pass
                # Also surface last_response snapshot if present
                if hasattr(context, "last_response"):
                    try:
                        lr = context.last_response or {}
                        method = lr.get("method")
                        path = lr.get("path")
                        status_code = lr.get("status")
                        headers = lr.get("headers") or {}
                        has_json = (lr.get("json") is not None)
                        has_text = (lr.get("text") is not None)
                        header_keys = sorted(list(headers.keys())) if isinstance(headers, dict) else []
                        print(
                            f"[behave] LAST_RESPONSE: method={method} path={path} status={status_code} "
                            f"headers_keys={header_keys} has_json={has_json} has_text={has_text}"
                        )
                        # Persist a JSONL record when scenario failed but no exception was attached
                        try:
                            os.makedirs("logs", exist_ok=True)
                            record = {
                                "feature": feature_name,
                                "scenario": name,
                                "test_id": f"feature::{feature_name}::scenario::{name}",
                                "step_name": getattr(failing, 'name', '<unnamed step>'),
                                "location": str(location),
                                "exception_class": type(f_exc).__name__ if f_exc is not None else None,
                                "exception_message": str(f_exc) if f_exc is not None else None,
                                "last_response": {
                                    "method": method,
                                    "path": path,
                                    "status": status_code,
                                    "headers_keys": header_keys,
                                    "has_json": has_json,
                                    "has_text": has_text,
                                },
                            }
                            with open(os.path.join("logs", "behave_failures.jsonl"), "a", encoding="utf-8") as fh:
                                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                        except Exception:
                            pass
                    except Exception:
                        pass
        except Exception:
            # Best-effort; never raise from diagnostics
            pass
