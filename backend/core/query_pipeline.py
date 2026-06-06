"""
QueryPipeline:

    Sequence:
        1. Check cache — return immediately on hit
        2. Embed query (dense + sparse) in parallel with loading conversation history
        3. Hybrid search in Qdrant (top-20)
        4. Rerank (top-20 → top-5)
        5. Build context window (token budget enforced)
        6. Generate answer via LLM (streaming)
        7. Fire observers (cache write, trace, metrics) — fire-and-forget
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from backend.core.context_window_builder import ContextWindowBuilder
from backend.exceptions import KapaError
from backend.models import ContextWindow, QueryResult, Turn
from backend.observers.base import QueryObserver
from backend.observers.error_metrics import rag_errors_total
from backend.repositories.base import ConversationRepository, SourceHashRepository
from backend.strategies.base import (
    CacheStrategy,
    EmbeddingStrategy,
    LLMStrategy,
    RerankerStrategy,
    SparseEncoderStrategy,
    VectorDBStrategy,
)

logger = logging.getLogger(__name__)

_TOP_K_RETRIEVAL = 20
_TOP_N_RERANK = 5
_CACHE_TTL_SECONDS = 3600


class QueryPipeline:
    """
    Orchestrates the full query flow from raw question to streamed answer.
    """

    def __init__(
        self,
        llm: LLMStrategy,
        embedder: EmbeddingStrategy,
        sparse_encoder: SparseEncoderStrategy,
        vector_db: VectorDBStrategy,
        reranker: RerankerStrategy,
        cache: CacheStrategy,
        conversation_repo: ConversationRepository,
        observers: list[QueryObserver],
        source_hash_repo: SourceHashRepository | None = None,
    ) -> None:
        self._llm = llm
        self._embedder = embedder
        self._sparse_encoder = sparse_encoder
        self._vector_db = vector_db
        self._reranker = reranker
        self._cache = cache
        self._conversation_repo = conversation_repo
        self._observers = observers
        self._source_hash_repo = source_hash_repo
        self._context_builder = ContextWindowBuilder()

    async def handle(
        self,
        query: str,
        tenant_id: str,
        conversation_id: UUID,
    ) -> QueryResult:
        """Run the full pipeline and return a complete (non-streamed) answer."""
        cache_key = _cache_key(query, tenant_id)
        cached_result = await self._cache.get(cache_key)
        if cached_result:
            logger.info("cache_hit tenant=%s", tenant_id)
            stub = ContextWindow(
                query=query, tenant_id=tenant_id, chunks=cached_result.source_chunks
            )
            asyncio.create_task(self._run_observers(stub, cached_result))
            return cached_result

        try:
            context = await self._build_context(query, tenant_id, conversation_id)
            result = await self._llm.generate(context)
        except KapaError as exc:
            rag_errors_total.labels(
                component=exc.component, error_type=exc.error_code.value
            ).inc()
            logger.error(
                "query failed: component=%s error_code=%s tenant=%s: %s",
                exc.component, exc.error_code, tenant_id, exc,
            )
            raise

        result.conversation_id = conversation_id

        asyncio.create_task(self._run_observers(context, result))
        asyncio.create_task(self._cache.set(cache_key, result, _CACHE_TTL_SECONDS))
        asyncio.create_task(self._save_turn(query, result.answer, conversation_id, tenant_id))

        return result

    async def handle_stream(
        self,
        query: str,
        tenant_id: str,
        conversation_id: UUID,
    ) -> AsyncIterator[str]:
        """Stream answer tokens as they arrive. Used for SSE responses."""
        cache_key = _cache_key(query, tenant_id)
        cached_result = await self._cache.get(cache_key)
        if cached_result:
            logger.info("cache_hit tenant=%s", tenant_id)
            stub = ContextWindow(
                query=query, tenant_id=tenant_id, chunks=cached_result.source_chunks
            )
            asyncio.create_task(self._run_observers(stub, cached_result))
            yield cached_result.answer
            return

        try:
            context = await self._build_context(query, tenant_id, conversation_id)
            full_answer: list[str] = []
            async for token in self._llm.generate_stream(context):
                full_answer.append(token)
                yield token
        except KapaError as exc:
            rag_errors_total.labels(
                component=exc.component, error_type=exc.error_code.value
            ).inc()
            logger.error(
                "stream failed: component=%s error_code=%s tenant=%s: %s",
                exc.component, exc.error_code, tenant_id, exc,
            )
            raise

        result = QueryResult(
            answer="".join(full_answer),
            source_chunks=context.chunks,
            conversation_id=conversation_id,
            cached=False,
        )

        asyncio.create_task(self._run_observers(context, result))
        asyncio.create_task(self._cache.set(cache_key, result, _CACHE_TTL_SECONDS))
        asyncio.create_task(self._save_turn(query, result.answer, conversation_id, tenant_id))

    async def _build_context(
        self,
        query: str,
        tenant_id: str,
        conversation_id: UUID,
    ) -> ContextWindow:
        """Embed query, retrieve chunks, rerank, load history — all in parallel where possible."""

        # embed + load history + source lookup run concurrently
        async def _no_sources() -> list:
            return []

        source_coro = (
            self._source_hash_repo.list_by_tenant(tenant_id)
            if self._source_hash_repo
            else _no_sources()
        )
        (dense_vec, sparse_pairs), recent_turns, tenant_sources = await asyncio.gather(
            self._embed_query(query),
            self._conversation_repo.get_recent_turns(conversation_id, limit=3),
            source_coro,
        )

        sparse_indices, sparse_values = sparse_pairs[0]

        chunks = await self._vector_db.hybrid_search(
            tenant_id=tenant_id,
            dense_vector=dense_vec[0],
            sparse_indices=sparse_indices,
            sparse_values=sparse_values,
            top_k=_TOP_K_RETRIEVAL,
        )

        reranked = await self._reranker.rerank(query, chunks, top_n=_TOP_N_RERANK)

        context = self._context_builder.build(
            query=query,
            chunks=reranked,
            history=recent_turns,
            tenant_id=tenant_id,
        )
        context.tenant_sources = tenant_sources
        return context

    async def _embed_query(
        self, query: str
    ) -> tuple[list[list[float]], list[tuple[list[int], list[float]]]]:
        """Run dense and sparse encoding in parallel."""
        return await asyncio.gather(
            self._embedder.embed([query]),
            self._sparse_encoder.encode([query]),
        )

    async def _run_observers(self, context: ContextWindow, result: QueryResult) -> None:
        tasks = [obs.notify(context, result) for obs in self._observers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for exc in results:
            if isinstance(exc, Exception):
                logger.warning("observer failed: %s", exc)

    async def _save_turn(
        self,
        query: str,
        answer: str,
        conversation_id: UUID,
        tenant_id: str,
    ) -> None:
        turn = Turn(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            user_message=query,
            assistant_message=answer,
        )
        try:
            await self._conversation_repo.save_turn(turn)
        except Exception as exc:
            logger.warning("failed to save turn: %s", exc)


def _cache_key(query: str, tenant_id: str) -> str:
    raw = f"{tenant_id}:{query}".encode()
    return f"cache:{hashlib.sha256(raw).hexdigest()}"














