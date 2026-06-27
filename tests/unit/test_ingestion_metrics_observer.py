from __future__ import annotations

import pytest

from backend.models import IngestionJob
from backend.observers.ingestion_metrics import IngestionMetricsObserver


def _make_job(tenant_id: str = "t1") -> IngestionJob:
    return IngestionJob(tenant_id=tenant_id)


class TestIngestionMetricsObserver:
    @pytest.mark.asyncio
    async def test_job_completed_increments_without_error(self):
        observer = IngestionMetricsObserver()
        job = _make_job()
        await observer.on_job_completed(job, chunks_processed=10)

    @pytest.mark.asyncio
    async def test_job_completed_zero_chunks(self):
        observer = IngestionMetricsObserver()
        job = _make_job(tenant_id="t2")
        await observer.on_job_completed(job, chunks_processed=0)

    @pytest.mark.asyncio
    async def test_job_failed_increments_without_error(self):
        observer = IngestionMetricsObserver()
        job = _make_job()
        await observer.on_job_failed(job, error=ValueError("connection timeout"))

    @pytest.mark.asyncio
    async def test_different_tenants_tracked_independently(self):
        observer = IngestionMetricsObserver()
        await observer.on_job_completed(_make_job("tenant-a"), chunks_processed=5)
        await observer.on_job_completed(_make_job("tenant-b"), chunks_processed=3)
        await observer.on_job_failed(_make_job("tenant-a"), error=RuntimeError("oops"))
