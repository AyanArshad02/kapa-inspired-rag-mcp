from __future__ import annotations

import asyncio
import time

import cohere

from backend.config import settings
from backend.exceptions import RerankerFailedError, RerankerTimeoutError
from backend.models import Chunk
from backend.strategies.base import RerankerStrategy

# Cohere free tier: 100 calls/minute. Stay at 90 to leave headroom.
_MAX_CALLS_PER_MINUTE = 90
_MIN_INTERVAL = 60.0 / _MAX_CALLS_PER_MINUTE  # ~0.67 s between calls
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds — doubles on each 429


class CohereReranker(RerankerStrategy):
    """Cohere rerank-english-v3.0 — cross-encoder, top-20 → top-n.

    Rate-limited to 90 calls/minute (free tier cap is 100).
    Retries up to 3 times with exponential backoff on 429 responses.
    """

    def __init__(self) -> None:
        self._client = cohere.AsyncClient(api_key=settings.cohere_api_key)
        # Semaphore ensures only one in-flight call at a time per instance,
        # combined with _min_interval enforces the per-minute limit.
        self._semaphore = asyncio.Semaphore(1)
        self._last_call_at: float = 0.0

    async def rerank(self, query: str, chunks: list[Chunk], top_n: int = 5) -> list[Chunk]:
        if not chunks:
            return []

        for attempt in range(_MAX_RETRIES):
            async with self._semaphore:
                await self._wait_for_slot()
                try:
                    response = await self._client.rerank(
                        model="rerank-english-v3.0",
                        query=query,
                        documents=[c.content for c in chunks],
                        top_n=min(top_n, len(chunks)),
                    )
                    result_chunks = []
                    for r in response.results:
                        chunk = chunks[r.index]
                        chunk.rerank_score = r.relevance_score
                        result_chunks.append(chunk)
                    return result_chunks
                except Exception as exc:
                    msg = str(exc).lower()
                    if "timeout" in msg or "timed out" in msg:
                        raise RerankerTimeoutError(str(exc)) from exc
                    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
                        if attempt < _MAX_RETRIES - 1:
                            delay = _RETRY_BASE_DELAY * (2**attempt)
                            await asyncio.sleep(delay)
                            continue
                        raise RerankerFailedError(
                            f"Cohere rate limit exceeded after {_MAX_RETRIES} retries"
                        ) from exc
                    raise RerankerFailedError(str(exc)) from exc

        raise RerankerFailedError("Cohere rerank failed after all retries")

    async def _wait_for_slot(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_call_at
        if elapsed < _MIN_INTERVAL:
            await asyncio.sleep(_MIN_INTERVAL - elapsed)
        self._last_call_at = time.monotonic()


class PassthroughReranker(RerankerStrategy):
    """No-op reranker — returns the first top_n chunks unchanged.

    Used in unit tests and local dev when Cohere key is not available.
    """

    async def rerank(self, query: str, chunks: list[Chunk], top_n: int = 5) -> list[Chunk]:
        return chunks[:top_n]
