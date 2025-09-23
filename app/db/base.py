"""Database bootstrap primitives (no ORM dependency).

This module provides:
- A minimal connection URL parser
- TLS enforcement flags derived from configuration

It intentionally avoids importing any driver to keep EPIC-A scope focused on
data model & migrations while still being testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlparse, parse_qsl, urlunparse, urlencode

from app.config import load_config


@dataclass(frozen=True)
class ConnectionInfo:
    scheme: str
    username: Optional[str]
    password: Optional[str]
    host: Optional[str]
    port: Optional[int]
    database: Optional[str]
    options: Dict[str, str]

    def with_option(self, key: str, value: str) -> "ConnectionInfo":
        new_opts = dict(self.options)
        new_opts[key] = value
        return ConnectionInfo(
            scheme=self.scheme,
            username=self.username,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
            options=new_opts,
        )

    def as_url(self) -> str:
        netloc = ""
        if self.username:
            auth = self.username
            if self.password:
                auth += f":{self.password}"
            netloc = auth + "@"
        if self.host:
            netloc += self.host
        if self.port:
            netloc += f":{self.port}"
        path = f"/{self.database}" if self.database else ""
        query = urlencode(self.options)
        return urlunparse((self.scheme, netloc, path, "", query, ""))


def parse_dsn(dsn: str) -> ConnectionInfo:
    """Parse DSN into structured fields with options map.

    Supports URLs like postgresql://user:pass@host:5432/db?sslmode=require
    """
    u = urlparse(dsn)
    options = dict(parse_qsl(u.query))
    port = u.port if u.port else None
    return ConnectionInfo(
        scheme=u.scheme,
        username=u.username,
        password=u.password,
        host=u.hostname,
        port=int(port) if port else None,
        database=u.path[1:] if u.path else None,
        options=options,
    )


def connection_info_with_tls() -> ConnectionInfo:
    """Return connection info adjusted for TLS enforcement if configured."""
    cfg = load_config()
    info = parse_dsn(cfg.database.dsn)
    if cfg.database.ssl_required:
        # Common envs: Postgres honors `sslmode=require` (psycopg/asyncpg)
        info = info.with_option("sslmode", info.options.get("sslmode", "require"))
    return info


__all__ = [
    "ConnectionInfo",
    "parse_dsn",
    "connection_info_with_tls",
]

