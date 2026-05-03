from __future__ import annotations

from openai import APIError, APITimeoutError, AsyncOpenAI, BadRequestError, RateLimitError

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.exceptions import EmbeddingBatchTooLargeError, EmbeddingFailedError
from backend.strategies.base import EmbeddingStrategy

_BATCH_SIZE = 100  # SENDIG 100 CHUNKS IN PER API REQUEST


class OpenAIEmbedding(EmbeddingStrategy):
    """Dense embeddings via text-embedding-3-small.

    Batches inputs to stay within OpenAI's per-request limits.
    All calls go through a circuit breaker so sustained failures
    trip open and surface immediately rather than hanging.
    """

    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_embedding_model
        self._circuit = CircuitBreaker(
            "openai-embedding", failure_threshold=5, recovery_timeout=30.0
        )

    @property
    def dimension(self) -> int:
        return settings.openai_embedding_dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float]] = []
        for batch in _batched(texts, _BATCH_SIZE):
            vecs = await self._circuit.call(self._call_api, batch)
            results.extend(vecs)
        return results

    async def _call_api(self, texts: list[str]) -> list[list[float]]:
        try:
            response = await self._client.embeddings.create(
                model=self._model,
                input=texts,
            )
        except CircuitOpenError as exc:
            raise EmbeddingFailedError("Embedding circuit open — too many recent failures") from exc
        except BadRequestError as exc:
            raise EmbeddingBatchTooLargeError(str(exc)) from exc
        except (RateLimitError, APITimeoutError, APIError) as exc:
            raise EmbeddingFailedError(str(exc)) from exc

        return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


def _batched(items: list, size: int):
    for i in range(0, len(items), size):
        yield items[i : i + size]






        
