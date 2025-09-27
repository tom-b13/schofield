"""Configuration utilities for EPIC-B.

This module loads application configuration with the following rules:
- Primary source: `cadence_config.json` at the project root.
- Overrides: environment variables, then optional text files under `config/`.
- Validation: Pydantic models enforce required fields and value constraints.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, ValidationError as PydanticValidationError, field_validator


CONFIG_DIR = Path("config")
ROOT_CADENCE_CONFIG = Path("cadence_config.json")
logger = logging.getLogger(__name__)


def _read_config_file(rel_path: str) -> Optional[str]:
    path = CONFIG_DIR / rel_path
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as e:
        # Recoverable: log and ignore unreadable override per AGENTS.md
        logger.warning("Failed to read override %s: %s", path, e)
        return None
    return None


def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(key, default)

class DatabaseConfig(BaseModel):
    dsn: str
    ssl_required: bool = Field(default=True)

    @field_validator("dsn")
    @classmethod
    def dsn_must_be_non_empty(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("database.dsn must be a non-empty string")
        return v


class EncryptionConfig(BaseModel):
    mode: str  # one of: tde, column, tde+column
    kms_key_alias: Optional[str] = None

    @field_validator("mode")
    @classmethod
    def mode_must_be_allowed(cls, v: str) -> str:
        allowed = {"tde", "column", "tde+column"}
        if v not in allowed:
            raise ValueError(f"encryption.mode must be one of {sorted(allowed)}")
        return v


class CsvConfig(BaseModel):
    import_max_bytes: int = Field(gt=0)
    export_include_header: bool = Field(default=True)


class AppConfig(BaseModel):
    database: DatabaseConfig
    encryption: EncryptionConfig
    csv: CsvConfig


def _read_json_file(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:  # pragma: no cover - defensive
        logger.error("Failed to read JSON config %s: %s", path, e)
    return {}


def load_config() -> AppConfig:
    """Load configuration with validation.

    Precedence (highest first):
    1) Environment variables
    2) Text files in `config/` (optional)
    3) cadence_config.json at project root (primary base)
    4) Safe defaults for development
    """

    base = _read_json_file(ROOT_CADENCE_CONFIG)

    # Helpers to fetch from base JSON
    def _base(path: str, default: Optional[str] = None) -> Optional[str]:
        cur: object = base
        for key in path.split("."):
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
        return str(cur) if cur is not None else default

    # Database
    dsn = _env("DATABASE_URL") or _read_config_file("database.url") or _base("database.dsn") or "postgresql://localhost/postgres"
    ssl_required_text = _env("DATABASE_SSL_REQUIRED") or _read_config_file("database.ssl.required") or _base("database.ssl_required", "true")
    ssl_required = str(ssl_required_text).strip().lower() == "true"

    # Encryption
    enc_mode = (_env("ENCRYPTION_MODE") or _read_config_file("encryption.mode") or _base("encryption.mode", "tde")).strip()
    kms_alias = _env("KMS_KEY_ALIAS") or _read_config_file("kms.key_alias") or _base("encryption.kms_key_alias")

    # CSV/import-export
    import_max_bytes_text = _env("CSV_IMPORT_MAX_BYTES") or _read_config_file("csv.import.max_bytes") or _base("csv.import_max_bytes", "10485760")
    export_include_header_text = _env("CSV_EXPORT_INCLUDE_HEADER") or _read_config_file("csv.export.include_header") or _base("csv.export_include_header", "true")

    try:
        csv_cfg = CsvConfig(
            import_max_bytes=int(str(import_max_bytes_text).strip()),
            export_include_header=str(export_include_header_text).strip().lower() == "true",
        )
        cfg = AppConfig(
            database=DatabaseConfig(dsn=dsn, ssl_required=ssl_required),
            encryption=EncryptionConfig(mode=enc_mode, kms_key_alias=kms_alias),
            csv=csv_cfg,
        )
        return cfg
    except PydanticValidationError as e:
        # Surface actionable message per AGENTS.md
        logger.error("Invalid application configuration: %s", e)
        raise


__all__ = [
    "AppConfig",
    "DatabaseConfig",
    "EncryptionConfig",
    "CsvConfig",
    "load_config",
]
