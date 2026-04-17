FROM python:3.11-slim AS base
WORKDIR /app
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
RUN pip install --no-cache-dir ".[dev]"
COPY backend/ ./backend/
COPY eval/ ./eval/

FROM base AS ingestion
CMD ["uvicorn", "backend.api.ingestion_service:app", "--host", "0.0.0.0", "--port", "8001"]

FROM base AS query
CMD ["uvicorn", "backend.api.query_service:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS mcp
CMD ["python", "-m", "backend.mcp.server"]

FROM base AS celery
# CMD is set per-container in docker-compose.yml
