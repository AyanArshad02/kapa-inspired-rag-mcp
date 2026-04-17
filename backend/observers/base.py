"""Observer interface for post-query side effects.

Observers are fire-and-forget. They run after the response is already sent
via asyncio.create_task — a failure here must never reach the caller.

Three concrete implementations come in Phase 2:
  CacheObserver   — writes result to Redis
  TraceObserver   — sends trace to LangSmith
  MetricsObserver — increments Prometheus counters
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.models import ContextWindow, QueryResult


class QueryObserver(ABC):
    """Notified once per completed query."""

    @abstractmethod
    async def notify(self, context: ContextWindow, result: QueryResult) -> None:
        ...
