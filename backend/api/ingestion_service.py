from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import UUID

import asyncpg
from fastapi import Depends, FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, HttpUrl

from backend.api.middleware.auth import get_tenant_id
from backend.config import settings
from backend.models import IngestionJob, IngestionStatus, SourceType
from backend.repositories.postgres_ingestion_job_repo import PostgresIngestionJobRepository
from backend.strategies.queue.celery_redis_queue import CeleryRedisQueue

app = FastAPI(title="kapa-rag ingestion service")
_queue = CeleryRedisQueue()


@app.on_event("startup")
async def startup() -> None:
    pool = await asyncpg.create_pool(settings.postgres_url.replace("+asyncpg", ""))
    app.state.db_pool = pool
    app.state.job_repo = PostgresIngestionJobRepository(pool)

    from backend.repositories.base import TenantRepository
    from backend.repositories.postgres_tenant_repo import PostgresTenantRepository
    app.state.tenant_repo = PostgresTenantRepository(pool)


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.db_pool.close()


# ── Request / Response models ─────────────────────────────────────────────────

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


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/ingest", response_model=IngestResponse, status_code=202)
async def submit_ingestion_job(
    body: IngestRequest,
    tenant_id: str = Depends(get_tenant_id),
) -> IngestResponse:
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
    """Accept a .pdf or .md file upload and queue it for ingestion."""
    filename = file.filename or ""
    suffix = Path(filename).suffix.lower()
    if suffix not in {".pdf", ".md"}:
        raise HTTPException(status_code=422, detail="Only .pdf and .md files are supported")

    content = await file.read()

    # NamedTemporaryFile with delete=False so the Celery worker (separate process) can open it.
    with tempfile.NamedTemporaryFile(
        suffix=suffix, delete=False, dir="/tmp"
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    source_type = SourceType.PDF if suffix == ".pdf" else SourceType.DOCS_SITE
    job = IngestionJob(
        tenant_id=tenant_id,
        source_url=tmp_path,
        source_type=source_type,
    )
    repo: PostgresIngestionJobRepository = app.state.job_repo
    await repo.create(job)
    await _queue.enqueue(job)
    return IngestResponse(job_id=job.id, status=job.status)


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


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}









