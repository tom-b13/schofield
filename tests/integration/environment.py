"""Behave environment hooks for integration tests.

Loads environment variables from a local .env (if present) and fails fast
when required variables are missing. Integration tests require a running API
and a real database; provide `TEST_BASE_URL` and `TEST_DATABASE_URL`.
"""

from __future__ import annotations

import os
from typing import Any
import httpx
from sqlalchemy import create_engine, text


def _maybe_load_dotenv() -> None:
    """Load env from .env and tests/integration/.env.test without hard dependency.

    - Prefer python-dotenv when available.
    - Fall back to a minimal line parser for tests/integration/.env.test so that
      TEST_MOCK_MODE=true is honored in CI environments that don't pre-load env.
    """
    try:
        from dotenv import load_dotenv  # type: ignore

        # Load default .env first (if present), without overriding explicit env vars
        load_dotenv(override=False)
        # Also load integration-specific defaults to enable mock mode in CI/local runs
        # without requiring TEST_BASE_URL/TEST_DATABASE_URL.
        load_dotenv(dotenv_path="tests/integration/.env.test", override=False)
        return
    except Exception:
        # If python-dotenv is not installed, fall back to manual .env.test parsing.
        pass

    # Fallback loader: parse tests/integration/.env.test (KEY=VALUE lines)
    env_path = os.path.join("tests", "integration", ".env.test")
    try:
        with open(env_path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                # Do not override existing environment variables
                if key and os.environ.get(key) is None:
                    os.environ[key] = val
    except FileNotFoundError:
        # No integration env file present; nothing to load.
        pass


def _require(name: str) -> str:
    val = os.environ.get(name)
    assert val and isinstance(val, str) and val.strip(), f"Environment variable {name} is required"
    return val


def before_all(context: Any) -> None:  # pragma: no cover - executed by Behave
    _maybe_load_dotenv()

    # Honor mock mode: when enabled, skip env requirements and connectivity checks.
    mock_mode = os.environ.get("TEST_MOCK_MODE", "").strip().lower() in {"1", "true", "yes", "on"}
    if mock_mode:
        print("[env] mock-mode enabled; skipping API/DB checks")
        return

    # Fail fast with clear errors if variables are not set
    base_url = _require("TEST_BASE_URL").rstrip("/")
    db_url = _require("TEST_DATABASE_URL")

    # Reachability checks
    try:
        with httpx.Client(timeout=5.0) as client:
            client.get(base_url + "/", headers={"Accept": "*/*"})
    except Exception as exc:
        raise AssertionError(f"API not reachable at TEST_BASE_URL={base_url}: {exc}")

    try:
        eng = create_engine(db_url, future=True)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise AssertionError("Database not reachable using TEST_DATABASE_URL: %s" % exc)
