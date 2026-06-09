from __future__ import annotations

import time

from prometheus_client import Counter, Histogram

from backend.models import ContextWindow, QueryResult
from backend.observers.base import QueryObserver

_query_latency = Histogram(
    "rag_query_latency_seconds",
    "End-to-end query pipeline latency (cache hit or full pipeline)",
    ["tenant_id"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0],
)

_cache_hits = Counter(
    "rag_cache_hits_total",
    "Queries served from the semantic cache (no LLM call)",
    ["tenant_id"],
)

_cache_misses = Counter(
    "rag_cache_misses_total",
    "Queries that missed the cache and ran the full pipeline",
    ["tenant_id"],
)


_retrieval_score = Histogram(
    "rag_retrieval_score",
    "Cohere rerank relevance score of the top chunk (0-1, proxy for retrieval quality)",
    ["tenant_id"],
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

_stage_latency = Histogram(
    "rag_pipeline_stage_latency_seconds",
    "Per-stage latency: embed / retrieve / rerank / generate",
    ["tenant_id", "stage"],
    buckets=[0.02, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

_query_total = Counter(
    "rag_queries_total",
    "Total number of queries handled",
    ["tenant_id", "cached"],
)

_query_tokens = Histogram(
    "rag_query_tokens",
    "Token count of the assembled context window (full pipeline only)",
    buckets=[100, 250, 500, 1000, 2000, 4000, 6000],
)

_source_chunks = Histogram(
    "rag_source_chunks_returned",
    "Number of source chunks included in the answer",
    buckets=[1, 2, 3, 4, 5],
)


class MetricsObserver(QueryObserver):
    """
    Publishes Prometheus metrics after every query.

    Receives a ContextWindow populated by QueryPipeline with:
      - pipeline_started_at   float  perf_counter at pipeline entry
      - pipeline_stage_latencies  dict  {"embed": 0.12, "retrieve": 0.3, ...}
      - top_retrieval_score   float  Cohere score of first reranked chunk

    All observe() / inc() calls are synchronous and microsecond-level — safe
    to call in the fire-and-forget observer loop without await.
    """

    async def notify(self, context: ContextWindow, result: QueryResult) -> None:
        tenant = context.tenant_id

        # Total query counter (used for QPS panels in Grafana)
        _query_total.labels(tenant_id=tenant, cached=str(result.cached)).inc()

        # End-to-end latency — only meaningful if pipeline set the start time
        if context.pipeline_started_at > 0:
            elapsed = time.perf_counter() - context.pipeline_started_at
            _query_latency.labels(tenant_id=tenant).observe(elapsed)

        # Cache hit vs miss split
        if result.cached:
            _cache_hits.labels(tenant_id=tenant).inc()
        else:
            _cache_misses.labels(tenant_id=tenant).inc()
            # Token + chunk counts only meaningful for full pipeline runs
            _query_tokens.observe(context.total_tokens)
            _source_chunks.observe(len(result.source_chunks))

        # Retrieval quality — only present when reranker ran
        if context.top_retrieval_score > 0:
            _retrieval_score.labels(tenant_id=tenant).observe(context.top_retrieval_score)

        # Per-stage latency breakdown (embed / retrieve / rerank / generate)
        for stage, latency in context.pipeline_stage_latencies.items():
            _stage_latency.labels(tenant_id=tenant, stage=stage).observe(latency)
