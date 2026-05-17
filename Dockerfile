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

FROM base AS webhook
CMD ["uvicorn", "backend.api.webhook:app", "--host", "0.0.0.0", "--port", "8003"]

FROM base AS celery
# CMD is set per-container in docker-compose.yml

FROM base AS auth
CMD ["uvicorn", "backend.api.auth_service:app", "--host", "0.0.0.0", "--port", "8004"]

FROM python:3.11-slim AS streamlit
WORKDIR /app
COPY frontend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY frontend/ ./frontend/
CMD ["streamlit", "run", "frontend/app.py", "--server.port=8501", "--server.address=0.0.0.0"]

# ── Next.js frontend ──────────────────────────────────────────────────────────

FROM node:20-alpine AS nextjs-deps
WORKDIR /app
COPY frontend-next/package*.json ./
RUN npm ci

FROM node:20-alpine AS nextjs-builder
WORKDIR /app
COPY --from=nextjs-deps /app/node_modules ./node_modules
COPY frontend-next/ ./

ARG NEXT_PUBLIC_AUTH_URL=http://localhost:8004
ARG NEXT_PUBLIC_INGESTION_URL=http://localhost:8001
ARG NEXT_PUBLIC_QUERY_URL=http://localhost:8000
ENV NEXT_PUBLIC_AUTH_URL=$NEXT_PUBLIC_AUTH_URL \
    NEXT_PUBLIC_INGESTION_URL=$NEXT_PUBLIC_INGESTION_URL \
    NEXT_PUBLIC_QUERY_URL=$NEXT_PUBLIC_QUERY_URL

RUN npm run build

FROM node:20-alpine AS nextjs
WORKDIR /app
ENV NODE_ENV=production PORT=3001
COPY --from=nextjs-builder /app/.next/standalone ./
COPY --from=nextjs-builder /app/.next/static ./.next/static
COPY --from=nextjs-builder /app/public ./public
EXPOSE 3001
CMD ["node", "server.js"]
