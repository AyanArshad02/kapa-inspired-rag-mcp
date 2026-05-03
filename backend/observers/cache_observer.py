from __future__ import annotations

import hashlib

from backend.models import ContextWindow, QueryResult
from backend.observers.base import QueryObserver
from backend.strategies.base import CacheStrategy


class CacheObserver(QueryObserver):
    """Writes the completed query result to the cache after response is sent."""

    def __init__(self, cache: CacheStrategy, ttl_seconds: int = 3600) -> None:
        self._cache = cache
        self._ttl = ttl_seconds

    async def notify(self, context: ContextWindow, result: QueryResult) -> None:
        key = _cache_key(context.query, context.tenant_id)
        await self._cache.set(key, result, self._ttl)


def _cache_key(query: str, tenant_id: str) -> str:
    raw = f"{tenant_id}:{query}".encode()
    return f"cache:{hashlib.sha256(raw).hexdigest()}"
