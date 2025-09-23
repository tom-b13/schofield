"""Configuration utilities for EPIC-A.

Purpose:
- Provide deterministic configuration access for database and encryption flags
  without introducing external dependencies.

Notes:
- Values are sourced from environment variables with file-based overrides in
  the project `config/` directory to satisfy architectural requirements.
- Do not embed any SQL/DDL tokens here; this module is orthogonal to DDL.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


CONFIG_DIR = Path("config")


def _read_config_file(rel_path: str) -> Optional[str]:
    path = CONFIG_DIR / rel_path
    try:
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    except Exception:
        # Fail closed by ignoring unreadable overrides
        return None
    return None


def _env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.environ.get(key, default)


@dataclass(frozen=True)
class DatabaseConfig:
    dsn: str
    ssl_required: bool


@dataclass(frozen=True)
class EncryptionConfig:
    mode: str  # one of: tde, column, tde+column
    kms_key_alias: Optional[str]


@dataclass(frozen=True)
class AppConfig:
    database: DatabaseConfig
    encryption: EncryptionConfig


def load_config() -> AppConfig:
    """Load configuration from environment with file overrides.

    Priority:
    - Text files in `config/` if present
    - Environment variables
    - Safe defaults for development
    """

    # Database
    dsn = _env("DATABASE_URL") or _read_config_file("database.url") or "postgresql://localhost/postgres"
    ssl_required_text = _read_config_file("database.ssl.required") or _env("DATABASE_SSL_REQUIRED", "true")
    ssl_required = str(ssl_required_text).strip().lower() == "true"

    # Encryption
    enc_mode = (_read_config_file("encryption.mode") or _env("ENCRYPTION_MODE", "tde")).strip()
    kms_alias = _read_config_file("kms.key_alias") or _env("KMS_KEY_ALIAS")

    return AppConfig(
        database=DatabaseConfig(dsn=dsn, ssl_required=ssl_required),
        encryption=EncryptionConfig(mode=enc_mode, kms_key_alias=kms_alias),
    )


__all__ = [
    "AppConfig",
    "DatabaseConfig",
    "EncryptionConfig",
    "load_config",
]

