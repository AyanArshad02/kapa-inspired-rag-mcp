from __future__ import annotations

import json
from uuid import UUID

import asyncpg

from backend.models import IngestionJob, IngestionStatus, SourceType
from backend.repositories.base import IngestionJobRepository


class PostgresIngestionJobRepository(IngestionJobRepository):
    """
    PostgreSQL-backed ingestion job tracking.

    Receives a connection pool at construction — the pool is created once
    at app startup and shared across all requests.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def create(self, job: IngestionJob) -> IngestionJob:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO ingestion_jobs
                    (job_id, tenant_id, source_url, source_type, status, checkpoint)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                str(job.id),
                job.tenant_id,
                job.source_url,
                job.source_type.value,
                job.status.value,
                json.dumps(job.checkpoint),
            )
        return job

    async def get(self, job_id: UUID) -> IngestionJob | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM ingestion_jobs WHERE job_id = $1", str(job_id)
            )
        if not row:
            return None
        return _row_to_job(row)

    async def update_status(
        self,
        job_id: UUID,
        status: IngestionStatus,
        error_message: str | None = None,
        checkpoint: dict | None = None,
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ingestion_jobs
                SET status = $1,
                    error_message = $2,
                    checkpoint = COALESCE($3::jsonb, checkpoint),
                    updated_at = NOW()
                WHERE job_id = $4
                """,
                status.value,
                error_message,
                checkpoint,
                str(job_id),
            )

    async def increment_processed(self, job_id: UUID, count: int = 1) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE ingestion_jobs
                SET docs_processed = docs_processed + $1, updated_at = NOW()
                WHERE job_id = $2
                """,
                count,
                str(job_id),
            )


def _decode_jsonb(value) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return json.loads(value)


def _row_to_job(row: asyncpg.Record) -> IngestionJob:
    return IngestionJob(
        id=UUID(str(row["job_id"])),
        tenant_id=str(row["tenant_id"]),
        source_url=row["source_url"],
        source_type=SourceType(row["source_type"]),
        status=IngestionStatus(row["status"]),
        total_chunks=row.get("docs_processed", 0),
        error_message=row.get("error_message"),
        checkpoint=_decode_jsonb(row.get("checkpoint")),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )




