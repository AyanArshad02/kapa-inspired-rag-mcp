from __future__ import annotations

import time
from uuid import uuid4

import pytest
from prometheus_client import REGISTRY

from backend.models import Chunk, ContextWindow, QueryResult, SourceType
from backend.observers.metrics_observer import MetricsObserver


def _sample_value(sample_name: str, labels: dict[str, str]) -> float:
    """Read a single sample value from the Prometheus global registry.

    prometheus_client strips _total from Counter metric.name, so we match
    on sample.name (e.g. 'rag_cache_hits_total') not metric.name ('rag_cache_hits').
    """
    for metric in REGISTRY.collect():
        for sample in metric.samples:
            if sample.name == sample_name and all(
                sample.labels.get(k) == v for k, v in labels.items()
            ):
                return sample.value
    return 0.0


def _make_context(tenant: str = "t1", **kwargs) -> ContextWindow:
    return ContextWindow(
        query="What is DI?",
        tenant_id=tenant,
        chunks=[],
        total_tokens=300,
        **kwargs,
    )


def _make_result(cached: bool = False) -> QueryResult:
    return QueryResult(
        answer="Dependency injection is a pattern.",
        source_chunks=[
            Chunk(
                tenant_id="t1",
                source_url="https://docs.example.com",
                source_type=SourceType.DOCS_SITE,
                content="DI content.",
            )
        ],
        conversation_id=uuid4(),
        cached=cached,
    )


class TestMetricsObserver:
    @pytest.mark.asyncio
    async def test_cache_hit_increments_hits_counter(self):
        observer = MetricsObserver()
        tenant = f"test_hit_{uuid4().hex[:6]}"
        before = _sample_value("rag_cache_hits_total", {"tenant_id": tenant})

        ctx = _make_context(tenant=tenant)
        result = _make_result(cached=True)
        await observer.notify(ctx, result)

        after = _sample_value("rag_cache_hits_total", {"tenant_id": tenant})
        assert after == before + 1.0

    @pytest.mark.asyncio
    async def test_cache_miss_increments_misses_counter(self):
        observer = MetricsObserver()
        tenant = f"test_miss_{uuid4().hex[:6]}"
        before = _sample_value("rag_cache_misses_total", {"tenant_id": tenant})

        ctx = _make_context(tenant=tenant)
        result = _make_result(cached=False)
        await observer.notify(ctx, result)

        after = _sample_value("rag_cache_misses_total", {"tenant_id": tenant})
        assert after == before + 1.0

    @pytest.mark.asyncio
    async def test_hit_does_not_increment_misses(self):
        observer = MetricsObserver()
        tenant = f"test_nospill_{uuid4().hex[:6]}"

        ctx = _make_context(tenant=tenant)
        result = _make_result(cached=True)
        await observer.notify(ctx, result)

        misses = _sample_value("rag_cache_misses_total", {"tenant_id": tenant})
        assert misses == 0.0

    @pytest.mark.asyncio
    async def test_latency_observed_when_started_at_set(self):
        observer = MetricsObserver()
        tenant = f"test_lat_{uuid4().hex[:6]}"

        started = time.perf_counter() - 0.5  # simulate 500ms pipeline
        ctx = _make_context(tenant=tenant, pipeline_started_at=started)
        result = _make_result(cached=False)
        await observer.notify(ctx, result)

        # Histogram emits sample name "rag_query_latency_seconds_count"
        count = _sample_value("rag_query_latency_seconds_count", {"tenant_id": tenant})
        assert count == 1.0

    @pytest.mark.asyncio
    async def test_latency_not_observed_when_started_at_zero(self):
        observer = MetricsObserver()
        tenant = f"test_nolat_{uuid4().hex[:6]}"

        ctx = _make_context(tenant=tenant, pipeline_started_at=0.0)
        result = _make_result(cached=False)
        await observer.notify(ctx, result)

        count = _sample_value("rag_query_latency_seconds_count", {"tenant_id": tenant})
        assert count == 0.0

    @pytest.mark.asyncio
    async def test_retrieval_score_observed(self):
        observer = MetricsObserver()
        tenant = f"test_score_{uuid4().hex[:6]}"

        ctx = _make_context(tenant=tenant, top_retrieval_score=0.85)
        result = _make_result(cached=False)
        await observer.notify(ctx, result)

        count = _sample_value("rag_retrieval_score_count", {"tenant_id": tenant})
        assert count == 1.0

    @pytest.mark.asyncio
    async def test_retrieval_score_zero_not_observed(self):
        observer = MetricsObserver()
        tenant = f"test_noscore_{uuid4().hex[:6]}"

        ctx = _make_context(tenant=tenant, top_retrieval_score=0.0)
        result = _make_result(cached=False)
        await observer.notify(ctx, result)

        count = _sample_value("rag_retrieval_score_count", {"tenant_id": tenant})
        assert count == 0.0

    @pytest.mark.asyncio
    async def test_stage_latencies_observed(self):
        observer = MetricsObserver()
        tenant = f"test_stage_{uuid4().hex[:6]}"

        ctx = _make_context(
            tenant=tenant,
            pipeline_stage_latencies={
                "embed": 0.1, "retrieve": 0.3, "rerank": 0.05, "generate": 0.8
            },
        )
        result = _make_result(cached=False)
        await observer.notify(ctx, result)

        for stage in ("embed", "retrieve", "rerank", "generate"):
            count = _sample_value(
                "rag_pipeline_stage_latency_seconds_count",
                {"tenant_id": tenant, "stage": stage},
            )
            assert count == 1.0, f"stage '{stage}' not observed"

    @pytest.mark.asyncio
    async def test_queries_total_incremented(self):
        observer = MetricsObserver()
        tenant = f"test_total_{uuid4().hex[:6]}"

        ctx = _make_context(tenant=tenant)
        result = _make_result(cached=False)
        await observer.notify(ctx, result)

        # Counter sample name is always "rag_queries_total" (same as registered name)
        count = _sample_value("rag_queries_total", {"tenant_id": tenant, "cached": "False"})
        assert count == 1.0
