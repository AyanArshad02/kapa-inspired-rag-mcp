from __future__ import annotations

import cohere

from backend.config import settings
from backend.exceptions import RerankerFailedError, RerankerTimeoutError
from backend.models import Chunk
from backend.strategies.base import RerankerStrategy


class CohereReranker(RerankerStrategy):
    """Cohere rerank-english-v3.0 — cross-encoder, top-20 → top-n."""

    def __init__(self) -> None:
        self._client = cohere.AsyncClient(api_key=settings.cohere_api_key)

    async def rerank(self, query: str, chunks: list[Chunk], top_n: int = 5) -> list[Chunk]:
        if not chunks:
            return []
        try:
            response = await self._client.rerank(
                model="rerank-english-v3.0",
                query=query,
                documents=[c.content for c in chunks],
                top_n=min(top_n, len(chunks)),
            )
        except Exception as exc:
            msg = str(exc).lower()
            if "timeout" in msg or "timed out" in msg:
                raise RerankerTimeoutError(str(exc)) from exc
            raise RerankerFailedError(str(exc)) from exc
        return [chunks[r.index] for r in response.results]


class PassthroughReranker(RerankerStrategy):
    """No-op reranker — returns the first top_n chunks unchanged.

    Used in unit tests and local dev when Cohere key is not available.
    """

    async def rerank(self, query: str, chunks: list[Chunk], top_n: int = 5) -> list[Chunk]:
        return chunks[:top_n]
