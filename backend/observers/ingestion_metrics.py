from __future__ import annotations

from prometheus_client import Counter

from backend.models import IngestionJob
from backend.observers.base import IngestionObserver

_ingestion_jobs_total = Counter(
    "rag_ingestion_jobs_total",
    "Total ingestion jobs by tenant and status",
    ["tenant_id", "status"],
)

_ingestion_chunks_total = Counter(
    "rag_ingestion_chunks_total",
    "Total chunks ingested by tenant",
    ["tenant_id"],
)


class IngestionMetricsObserver(IngestionObserver):
    """Increments Prometheus counters when ingestion jobs finish."""

    async def on_job_completed(self, job: IngestionJob, chunks_processed: int) -> None:
        _ingestion_jobs_total.labels(tenant_id=job.tenant_id, status="completed").inc()
        _ingestion_chunks_total.labels(tenant_id=job.tenant_id).inc(chunks_processed)

    async def on_job_failed(self, job: IngestionJob, error: Exception) -> None:
        _ingestion_jobs_total.labels(tenant_id=job.tenant_id, status="failed").inc()
