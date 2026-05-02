"""Production logging setup — CloudWatch via watchtower.

Writes to two destinations:
  1. CloudWatch Logs  — JSON, for Insights queries and long-term retention
  2. stderr           — JSON, safety net so `docker logs` always works
                        even if the CloudWatch connection drops

CloudWatch structure:
  Log group:  settings.cloudwatch_log_group  (e.g. /kapa-rag/production)
  Log stream: service_name                   (e.g. query, ingestion)

IAM requirement: the EC2 instance role needs:
  logs:CreateLogGroup, logs:CreateLogStream, logs:PutLogEvents

watchtower sends logs asynchronously in batches — zero latency impact
on the request path.
"""
from __future__ import annotations

import logging
import sys

from backend.logging.base import LogSetup
from backend.logging.formatters import JSONFormatter

_NOISY_LOGGERS = ("httpx", "httpcore", "openai", "asyncio", "urllib3", "botocore", "boto3")


class ProdLogSetup(LogSetup):
    """CloudWatch + stderr handler for production EC2 deployments."""

    def configure(self, service_name: str) -> None:
        from backend.config import settings

        formatter = JSONFormatter(service_name)

        # stderr handler — always present as a fallback (Docker captures it)
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setFormatter(formatter)
        stderr_handler.setLevel(logging.INFO)

        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(stderr_handler)

        # CloudWatch handler — primary sink for structured log storage
        try:
            import boto3
            import watchtower

            cw_client = boto3.client("logs", region_name=settings.s3_region)
            cw_handler = watchtower.CloudWatchLogHandler(
                log_group=settings.cloudwatch_log_group,
                stream_name=service_name,
                boto3_client=cw_client,
                send_interval=5,       # flush every 5 seconds
                max_batch_size=100,    # or 100 records, whichever comes first
            )
            cw_handler.setFormatter(formatter)
            cw_handler.setLevel(logging.INFO)
            root.addHandler(cw_handler)
            logging.getLogger(__name__).info(
                "CloudWatch logging enabled | group=%s stream=%s",
                settings.cloudwatch_log_group,
                service_name,
            )
        except ImportError:
            logging.getLogger(__name__).warning(
                "watchtower not installed — CloudWatch logging disabled, "
                "falling back to stderr only"
            )
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "CloudWatch handler setup failed: %s — falling back to stderr only", exc
            )

        root.setLevel(logging.INFO)
        logging.getLogger("backend").setLevel(logging.INFO)

        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)
