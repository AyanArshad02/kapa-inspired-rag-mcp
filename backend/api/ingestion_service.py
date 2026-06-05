from __future__ import annotations

import logging
import os as _os
from pathlib import Path
from uuid import UUID

import asyncpg
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel, HttpUrl
from starlette.responses import Response as _PrometheusResponse

from backend.api.middleware.auth import get_tenant_id
from backend.config import settings
from backend.models import IngestionJob, IngestionStatus, SourceType
from backend.repositories.postgres_ingestion_job_repo import PostgresIngestionJobRepository
from backend.repositories.postgres_source_hash_repo import PostgresSourceHashRepository
from backend.strategies.queue.celery_redis_queue import CeleryRedisQueue
from backend.strategies.storage.s3_storage import S3Storage

logger = logging.getLogger(__name__)
app = FastAPI(title="kapa-rag ingestion service")

_ALLOWED_ORIGINS = [
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    *[o.strip() for o in _os.getenv("EXTRA_ALLOWED_ORIGINS", "").split(",") if o.strip()],
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/metrics", include_in_schema=False)
def metrics() -> _PrometheusResponse:
    return _PrometheusResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

_queue = CeleryRedisQueue()
_storage = S3Storage()


@app.on_event("startup")
async def startup() -> None:
    from backend.logging import LogSetupFactory
    LogSetupFactory.create(settings.environment).configure("ingestion")

    pool = await asyncpg.create_pool(settings.postgres_url.replace("+asyncpg", ""))
    app.state.db_pool = pool
    app.state.job_repo = PostgresIngestionJobRepository(pool)
    app.state.hash_repo = PostgresSourceHashRepository(pool)

    from backend.repositories.postgres_tenant_repo import PostgresTenantRepository
    app.state.tenant_repo = PostgresTenantRepository(pool)
    logger.info("ingestion service started")


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.db_pool.close()


# ── Request / Response models ──────────────────────────────────────────────────

class IngestRequest(BaseModel):
    source_url: HttpUrl
    source_type: SourceType


class IngestResponse(BaseModel):
    job_id: UUID
    status: IngestionStatus


class JobStatusResponse(BaseModel):
    job_id: UUID
    status: IngestionStatus
    processed_chunks: int
    error_message: str | None


class SourceRecord(BaseModel):
    source_url: str
    source_type: str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/ingest", response_model=IngestResponse, status_code=202)
async def submit_ingestion_job(
    body: IngestRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> IngestResponse:
    """Queue a GitHub repo or docs URL for ingestion."""
    job = IngestionJob(
        tenant_id=tenant_id,
        source_url=str(body.source_url),
        source_type=body.source_type,
    )
    repo: PostgresIngestionJobRepository = app.state.job_repo
    await repo.create(job)
    await _queue.enqueue(job)
    return IngestResponse(job_id=job.id, status=job.status)


@app.post("/ingest/upload", response_model=IngestResponse, status_code=202)
async def upload_and_ingest(
    file: UploadFile = File(...),
    tenant_id: str = Depends(get_tenant_id),
) -> IngestResponse:
    """Accept a .pdf or .md upload, store it in S3, then queue ingestion.

    Both file types are routed to PDFConnector:
      .pdf  → pymupdf4llm extraction → RecursiveChunker
      .md   → raw Markdown           → HeadingAwareChunker
    """
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".md"}:
        raise HTTPException(status_code=422, detail="Only .pdf and .md files are supported")

    content = await file.read()
    s3_url = await _storage.upload(content, tenant_id, filename)

    job = IngestionJob(
        tenant_id=tenant_id,
        source_url=s3_url,
        source_type=SourceType.PDF,  # PDFConnector handles both .pdf and .md
    )
    repo: PostgresIngestionJobRepository = app.state.job_repo
    await repo.create(job)
    await _queue.enqueue(job)
    return IngestResponse(job_id=job.id, status=job.status)


@app.delete("/ingest/upload", status_code=200)
async def delete_uploaded_file(
    source_url: str,
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Delete a tenant's uploaded file: removes S3 object + Qdrant chunks + hash record.

    Called when a tenant removes a PDF or Markdown file from the dashboard.
    """
    from backend.connectors.docs_connector import DocsConnector
    from backend.connectors.factory import ConnectorFactory
    from backend.connectors.github_connector import GitHubConnector
    from backend.connectors.pdf_connector import PDFConnector
    from backend.core.freshness_manager import FreshnessManager
    from backend.strategies.embedding.openai_embedding import OpenAIEmbedding
    from backend.strategies.embedding.tf_sparse_encoder import TFSparseEncoder
    from backend.strategies.vectordb.qdrant_db import QdrantDB

    factory = ConnectorFactory()
    factory.register(DocsConnector())
    factory.register(PDFConnector())
    factory.register(GitHubConnector())

    fm = FreshnessManager(
        connector_factory=factory,
        hash_repo=app.state.hash_repo,
        job_repo=app.state.job_repo,
        embedder=OpenAIEmbedding(),
        sparse_encoder=TFSparseEncoder(),
        vector_db=QdrantDB(),
    )
    await fm.purge_source(tenant_id, source_url)
    await _storage.delete(source_url)
    return {"status": "deleted", "source_url": source_url}


@app.get("/ingest/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
) -> JobStatusResponse:
    repo: PostgresIngestionJobRepository = app.state.job_repo
    job = await repo.get(job_id)

    if job is None or job.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Job not found")

    return JobStatusResponse(
        job_id=job.id,
        status=job.status,
        processed_chunks=job.total_chunks,
        error_message=job.error_message,
    )


@app.get("/sources", response_model=list[SourceRecord])
async def list_sources(
    tenant_id: str = Depends(get_tenant_id),
) -> list[SourceRecord]:
    """Return all indexed sources for the authenticated tenant.

    Used by the dashboard to display what's currently indexed and
    present a delete button next to each source.
    """
    hash_repo: PostgresSourceHashRepository = app.state.hash_repo
    rows = await hash_repo.list_by_tenant(tenant_id)
    return [SourceRecord(source_url=r["source_url"], source_type=r["source_type"]) for r in rows]


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
