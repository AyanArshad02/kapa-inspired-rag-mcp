"""Log formatters for dev and prod environments.

PlainTextFormatter — human-readable, for terminals and rotating log files.
JSONFormatter      — one JSON object per line, for CloudWatch Insights filtering.

CloudWatch Insights can filter JSON logs with queries like:
  fields @timestamp, error_type, tenant_id
  | filter level = "ERROR"
  | stats count(*) by error_type, bin(1h)
"""
from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timezone


class PlainTextFormatter(logging.Formatter):
    """Human-readable log lines for development.

    Format: HH:MM:SS | LEVEL    | logger.name | message
    """

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )


class JSONFormatter(logging.Formatter):
    """Structured JSON log lines for CloudWatch Insights.

    Every record becomes one JSON object with standard fields.
    KapaError fields (component, error_code) are surfaced automatically
    if they are attached to the log record via extra={}.

    Example output:
    {
        "timestamp": "2026-05-02T19:14:32.123456+00:00",
        "level": "ERROR",
        "service": "query",
        "logger": "backend.core.query_pipeline",
        "message": "LLM call failed after 30s",
        "component": "llm",
        "error_type": "LLMTimeoutError"
    }
    """

    # Fields attached via logger.error(..., extra={...}) that should be
    # promoted to top-level JSON keys for CloudWatch filtering.
    _EXTRA_FIELDS = ("component", "error_code", "error_type", "tenant_id", "job_id")

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for field in self._EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = str(value)

        if record.exc_info:
            payload["exception"] = "".join(traceback.format_exception(*record.exc_info))

        return json.dumps(payload, ensure_ascii=False)
