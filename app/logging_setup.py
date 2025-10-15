"""Central logging configuration for the application.

Applies a root stdout handler so all module loggers emit INFO-level logs
without requiring per-module setup. Keeps uvicorn loggers visible and avoids
duplicate handlers on reloads.
"""
from __future__ import annotations
import logging
from logging.config import dictConfig

_DICT_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s %(levelname)s:%(name)s:%(message)s",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": "INFO",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        }
    },
    "root": {"level": "INFO", "handlers": ["console"]},
    "loggers": {
        "uvicorn": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "uvicorn.error": {"level": "INFO", "handlers": ["console"], "propagate": False},
        "uvicorn.access": {"level": "INFO", "handlers": ["console"], "propagate": False},
    },
}

def configure_logging() -> None:
    """Configure application-wide logging once.

    If the root logger already has handlers, return to prevent duplicate output
    (important under reloaders/watchers).
    """
    root = logging.getLogger()
    if root.handlers:
        return
    dictConfig(_DICT_CONFIG)
