"""Connector interface — one implementation per source type."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from backend.models import Chunk, SourceType


class ConnectorStrategy(ABC):
    """Fetches raw content from a source and yields chunks.

    Each connector owns its ChunkerStrategy. The ingestion pipeline
    doesn't know or care which chunker is used internally — it only
    calls `fetch_chunks`.
    """

    @property
    @abstractmethod
    def source_type(self) -> SourceType:
        ...

    @abstractmethod
    async def fetch_chunks(
        self, source_url: str, tenant_id: str
    ) -> AsyncIterator[Chunk]:
        """Yield chunks as they are produced (memory-safe for large sources)."""
        ...

    @abstractmethod
    async def compute_content_hash(self, source_url: str) -> str:
        """Return a stable hash of the source's current state.

        Used by FreshnessManager to detect whether a full re-fetch is needed.
        A URL + last-modified header is usually sufficient.
        """
        ...
