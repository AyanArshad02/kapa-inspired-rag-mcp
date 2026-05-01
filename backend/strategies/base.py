from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from backend.models import Chunk, ContextWindow, IngestionJob, QueryResult


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


class EmbeddingStrategy(ABC):
    """Converts text into dense float vectors."""

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimensionality — needed when creating a Qdrant collection."""
        ...


# ---------------------------------------------------------------------------
# Sparse encoding (SPLADE / BM25)
# ---------------------------------------------------------------------------


class SparseEncoderStrategy(ABC):
    """Produces sparse term-weight vectors for hybrid retrieval."""

    @abstractmethod
    async def encode(
        self, texts: list[str]
    ) -> list[tuple[list[int], list[float]]]:
        """Return (indices, values) pairs, one per input text."""
        ...


# ---------------------------------------------------------------------------
# Vector store
# ---------------------------------------------------------------------------


class VectorDBStrategy(ABC):
    """Persistence and retrieval of chunk vectors."""

    @abstractmethod
    async def upsert(self, chunks: list[Chunk]) -> None:
        """Insert or update chunks. Idempotent on chunk.id."""
        ...

    @abstractmethod
    async def hybrid_search(
        self,
        tenant_id: str,
        dense_vector: list[float],
        sparse_indices: list[int],
        sparse_values: list[float],
        top_k: int = 20,
    ) -> list[Chunk]:
        """Run dense + sparse search with RRF fusion, return top_k chunks."""
        ...

    @abstractmethod
    async def delete_chunks(self, tenant_id: str, chunk_ids: list[str]) -> None:
        """Hard-delete chunks by id (used by FreshnessManager)."""
        ...

    @abstractmethod
    async def delete_by_filter(self, tenant_id: str, filter_dict: dict[str, str]) -> None:
        """Delete all chunks whose payload matches every key=value in filter_dict.

        Supports dot-notation for nested keys (e.g. ``metadata.file_path``).
        Used by FreshnessManager to purge a whole source or a single file.
        """
        ...

    @abstractmethod
    async def collection_exists(self, tenant_id: str) -> bool:
        ...

    @abstractmethod
    async def create_collection(self, tenant_id: str) -> None:
        ...


# ---------------------------------------------------------------------------
# Reranking
# ---------------------------------------------------------------------------


class RerankerStrategy(ABC):
    """Cross-encoder reranking: top-20 chunks → top-5."""

    @abstractmethod
    async def rerank(
        self, query: str, chunks: list[Chunk], top_n: int = 5
    ) -> list[Chunk]:
        """Return top_n chunks ordered by relevance to query."""
        ...


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


class LLMStrategy(ABC):
    """Grounded answer generation with streaming support."""

    @abstractmethod
    async def generate(self, context: ContextWindow) -> QueryResult:
        """Return a complete, non-streamed answer."""
        ...

    @abstractmethod
    def generate_stream(
        self, context: ContextWindow
    ) -> AsyncIterator[str]:
        """Yield answer tokens as they arrive (SSE-friendly)."""
        ...


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------


class ChunkerStrategy(ABC):
    """Splits raw source content into indexable chunks.

    Each connector owns one ChunkerStrategy. Different source types
    (docs, code, PDF, Slack) have fundamentally different structure,
    so chunking is NOT one-size-fits-all.
    """

    @abstractmethod
    def chunk(self, content: str, metadata: dict[str, Any]) -> list[Chunk]:
        """Return chunks with content and metadata populated.

        dense_vector / sparse_* are left empty — the Embedder fills those.
        """
        ...


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------


class QueueStrategy(ABC):
    """Task queue for async ingestion jobs."""

    @abstractmethod
    async def enqueue(self, job: IngestionJob) -> str:
        """Submit a job and return its task ID."""
        ...

    @abstractmethod
    async def get_status(self, task_id: str) -> IngestionStatus:
        ...


# keep the import clean
from backend.models import IngestionStatus  # noqa: E402


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


class CacheStrategy(ABC):
    """Read-through cache for query results."""

    @abstractmethod
    async def get(self, key: str) -> QueryResult | None:
        ...

    @abstractmethod
    async def set(self, key: str, result: QueryResult, ttl_seconds: int) -> None:
        ...

    @abstractmethod
    async def invalidate(self, key: str) -> None:
        ...


# ---------------------------------------------------------------------------
# Observer (async side-effects after answer generation)
# ---------------------------------------------------------------------------


class ObserverStrategy(ABC):
    """Fire-and-forget side effects after a query completes.

    Observers run after the response is sent. A failure here must never
    affect the caller.
    """

    @abstractmethod
    async def on_query_complete(
        self,
        context: ContextWindow,
        result: QueryResult,
    ) -> None:
        ...









