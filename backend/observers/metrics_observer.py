from __future__ import annotations

from prometheus_client import Counter, Histogram

from backend.models import ContextWindow, QueryResult
from backend.observers.base import QueryObserver

_query_total = Counter(
    "rag_queries_total",
    "Total number of queries handled",
    ["tenant_id", "cached"],
)

_query_tokens = Histogram(
    "rag_query_tokens",
    "Token count of the assembled context window",
    buckets=[100, 250, 500, 1000, 2000, 4000, 6000],
)

_source_chunks = Histogram(
    "rag_source_chunks_returned",
    "Number of source chunks included in the answer",
    buckets=[1, 2, 3, 4, 5],
)


class MetricsObserver(QueryObserver):
    """Increments Prometheus counters and histograms after each query."""

    async def notify(self, context: ContextWindow, result: QueryResult) -> None:
        _query_total.labels(
            tenant_id=context.tenant_id,
            cached=str(result.cached),
        ).inc()
        _query_tokens.observe(context.total_tokens)
        _source_chunks.observe(len(result.source_chunks))
