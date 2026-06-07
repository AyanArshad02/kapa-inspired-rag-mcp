from __future__ import annotations

from backend.models import ContextWindow, QueryResult
from backend.observers.base import QueryObserver
from backend.strategies.base import SemanticCacheStrategy


class CacheObserver(QueryObserver):
    """Writes the completed query result to the semantic cache after response is sent.

    Relies on context.query_embedding being populated by the pipeline.
    No-ops silently when the embedding is absent (e.g. in tests that don't
    pass a full context).
    """

    def __init__(self, cache: SemanticCacheStrategy, ttl_seconds: int = 3600) -> None:
        self._cache = cache
        self._ttl = ttl_seconds

    async def notify(self, context: ContextWindow, result: QueryResult) -> None:
        if not context.query_embedding:
            return
        await self._cache.set(
            context.query_embedding, context.tenant_id, result, self._ttl
        )
