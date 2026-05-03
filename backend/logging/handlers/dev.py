"""Development logging setup.

Writes to two destinations simultaneously:
  1. stdout    — plain text, for the terminal you're watching
  2. logs/{service}.log — same plain text, rotating file for post-mortem

The logs/ directory is created at startup if it doesn't exist.
logs/ is gitignored — never committed.

Rotation: 10 MB per file, 5 backups kept.
  logs/ingestion.log
  logs/ingestion.log.1  ← previous
  logs/ingestion.log.2
  ...
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from backend.logging.base import LogSetup
from backend.logging.formatters import PlainTextFormatter

# Project root is 3 levels up from this file:
# backend/logging/handlers/dev.py → parents[3]
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LOGS_DIR = _PROJECT_ROOT / "logs"

_NOISY_LOGGERS = ("httpx", "httpcore", "openai", "asyncio", "urllib3", "botocore", "boto3")


class DevLogSetup(LogSetup):
    """Stdout + rotating file handler for local development."""

    def configure(self, service_name: str) -> None:
        _LOGS_DIR.mkdir(exist_ok=True)

        formatter = PlainTextFormatter()

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(logging.DEBUG)

        file_handler = RotatingFileHandler(
            filename=_LOGS_DIR / f"{service_name}.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)

        root = logging.getLogger()
        # Remove existing handlers (uvicorn may have added its own)
        root.handlers.clear()
        root.addHandler(stream_handler)
        root.addHandler(file_handler)
        root.setLevel(logging.INFO)

        # Application loggers always at INFO
        logging.getLogger("backend").setLevel(logging.INFO)

        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)

        logging.getLogger(__name__).info(
            "logging configured | env=dev service=%s log_file=logs/%s.log",
            service_name,
            service_name,
        )
