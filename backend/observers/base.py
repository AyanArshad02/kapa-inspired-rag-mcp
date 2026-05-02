"""Observer interfaces for post-query and post-ingestion side effects.

Observers are fire-and-forget. They run after the response is already sent
via asyncio.create_task — a failure here must never reach the caller.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from backend.models import ContextWindow, IngestionJob, QueryResult


class QueryObserver(ABC):
    """Notified once per completed query."""

    @abstractmethod
    async def notify(self, context: ContextWindow, result: QueryResult) -> None:
        ...


class IngestionObserver(ABC):
    """Notified on ingestion job completion or failure."""

    @abstractmethod
    async def on_job_completed(self, job: IngestionJob, chunks_processed: int) -> None:
        ...

    @abstractmethod
    async def on_job_failed(self, job: IngestionJob, error: Exception) -> None:
        ...
