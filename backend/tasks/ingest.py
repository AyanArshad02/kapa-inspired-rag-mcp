from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from celery import Task

from backend.strategies.queue.celery_redis_queue import celery_app

logger = logging.getLogger(__name__)


class IngestionTask(Task):
    """
    Base task class that holds lazily initialised pipeline instance.

    Celery workers are long-lived processes. We build the pipeline once
    on first use (not at import time) so the worker starts fast and only
    pays the initialisation cost when the first job arrives.
    """

    _pipeline = None

    @property
    def pipeline(self):
        if self._pipeline is None:
            from backend.tasks._pipeline_factory import build_ingestion_pipeline
            self._pipeline = build_ingestion_pipeline()
        return self._pipeline


@celery_app.task(
    bind=True,
    base=IngestionTask,
    name="backend.tasks.ingest.run_ingestion_job",
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def run_ingestion_job(self, job_id: str) -> dict:
    """Entry point for Celery. Runs the async pipeline synchronously."""
    logger.info("worker picked up job=%s", job_id)
    try:
        asyncio.run(_run(self.pipeline, job_id))
        return {"status": "completed", "job_id": job_id}
    except Exception as exc:
        logger.error("job=%s failed: %s", job_id, exc)
        raise self.retry(exc=exc)


async def _run(pipeline, job_id: str) -> None:
    from backend.repositories.postgres_ingestion_job_repo import PostgresIngestionJobRepository
    from backend.tasks._pipeline_factory import get_db_pool

    pool = await get_db_pool()
    repo = PostgresIngestionJobRepository(pool)
    job = await repo.get(UUID(job_id))

    if job is None:
        raise ValueError(f"Job {job_id} not found in database")

    await pipeline.run(job)









