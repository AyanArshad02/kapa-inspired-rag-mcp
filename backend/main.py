"""Development entry point.

In production, Docker containers start services directly:
  uvicorn backend.api.ingestion_service:app --port 8001
  uvicorn backend.api.query_service:app --port 8000

Locally, this file lets you start any service with one command:
  python -m backend.main --service ingestion
  python -m backend.main --service query
"""

from __future__ import annotations

import argparse
import logging
import sys

import uvicorn

from backend.config import settings


def _validate_config() -> None:
    """Fail fast if required env vars are missing before any service starts."""
    errors = []
    if not settings.openai_api_key or settings.openai_api_key == "sk-placeholder":
        errors.append("OPENAI_API_KEY is not set")
    if not settings.qdrant_url:
        errors.append("QDRANT_URL is not set")
    if errors:
        for e in errors:
            logging.error("Config error: %s", e)
        sys.exit(1)


_SERVICE_MAP = {
    "ingestion": ("backend.api.ingestion_service:app", 8001),
    "query":     ("backend.api.query_service:app",     8000),
}


def main() -> None:
    parser = argparse.ArgumentParser(description="kapa-rag service runner")
    parser.add_argument(
        "--service",
        choices=list(_SERVICE_MAP.keys()),
        default="ingestion",
        help="Which service to start (default: ingestion)",
    )
    parser.add_argument("--reload", action="store_true", help="Enable hot reload")
    args = parser.parse_args()

    app_path, port = _SERVICE_MAP[args.service]

    logging.info("Starting %s service on port %d", args.service, port)

    if args.service != "query":
        _validate_config()

    uvicorn.run(
        app_path,
        host="0.0.0.0",
        port=port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
