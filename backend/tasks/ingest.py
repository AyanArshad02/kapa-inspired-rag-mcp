from __future__ import annotations

import asyncio
import logging
from uuid import UUID

import asyncpg

from backend.strategies.queue.celery_redis_queue import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="backend.tasks.ingest.run_ingestion_job",
    max_retries=3,
    default_retry_delay=60,
    acks_late=True,
)
def run_ingestion_job(self, job_id: str) -> dict:
    """Entry point for Celery. Runs the async pipeline in a fresh event loop."""
    from backend.exceptions import KapaError

    logger.info("worker picked up job=%s", job_id)
    try:
        asyncio.run(_run(job_id))
        return {"status": "completed", "job_id": job_id}
    except KapaError as exc:
        if exc.retryable:
            raise self.retry(exc=exc)
        logger.error(
            "job=%s non-retryable failure: component=%s error_code=%s",
            job_id, exc.component, exc.error_code,
        )
        return {"status": "failed", "job_id": job_id, "error_code": exc.error_code.value}
    except Exception as exc:
        logger.error("job=%s failed: %s", job_id, exc)
        raise self.retry(exc=exc)


async def _run(job_id: str) -> None:
    """
    Build the full pipeline inside the event loop that will use it.
    asyncpg pools are bound to the event loop they are created in —
    creating the pool here (not in the parent process) avoids the
    'another operation is in progress' fork-safety error.
    """
    from backend.config import settings
    from backend.connectors.docs_connector import DocsConnector
    from backend.connectors.factory import ConnectorFactory
    from backend.core.ingestion_pipeline import IngestionPipeline
    from backend.repositories.postgres_ingestion_job_repo import PostgresIngestionJobRepository
    from backend.strategies.embedding.openai_embedding import OpenAIEmbedding
    from backend.strategies.embedding.tf_sparse_encoder import TFSparseEncoder
    from backend.strategies.vectordb.qdrant_db import QdrantDB

    pool = await asyncpg.create_pool(settings.postgres_url.replace("+asyncpg", ""))
    try:
        repo = PostgresIngestionJobRepository(pool)
        job = await repo.get(UUID(job_id))
        if job is None:
            raise ValueError(f"Job {job_id} not found in database")

        from backend.connectors.github_connector import GitHubConnector
        from backend.connectors.pdf_connector import PDFConnector
        from backend.observers.ingestion_metrics import IngestionMetricsObserver
        from backend.repositories.postgres_source_hash_repo import PostgresSourceHashRepository

        hash_repo = PostgresSourceHashRepository(pool)

        factory = ConnectorFactory()
        factory.register(DocsConnector())
        factory.register(PDFConnector())
        factory.register(GitHubConnector())
        pipeline = IngestionPipeline(
            connector_factory=factory,
            embedder=OpenAIEmbedding(),
            sparse_encoder=TFSparseEncoder(),
            vector_db=QdrantDB(),
            job_repo=repo,
            observers=[IngestionMetricsObserver()],
        )
        await pipeline.run(job)

        # Record content hash so FreshnessManager can detect stale sources
        connector = factory.get(job.source_type)
        content_hash = await connector.compute_content_hash(job.source_url)
        await hash_repo.upsert(
            job.tenant_id, job.source_url, content_hash, job.source_type.value
        )
        logger.info("job=%s completed source_hash recorded", job_id)
    finally:
        await pool.close()









