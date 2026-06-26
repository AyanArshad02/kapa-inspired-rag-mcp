from __future__ import annotations

import json
import logging
import os as _os
from decimal import Decimal
from uuid import UUID, uuid4

import asyncpg
import redis.asyncio as aioredis
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from starlette.responses import Response as _PrometheusResponse

from backend.api.admin_service import router as admin_router
from backend.api.dependencies import rate_limit
from backend.api.middleware.auth import get_tenant_id
from backend.config import settings
from backend.core.query_pipeline import QueryPipeline
from backend.observers.cache_observer import CacheObserver
from backend.observers.metrics_observer import MetricsObserver
from backend.observers.trace_observer import TraceObserver
from backend.observers.usage_observer import UsageObserver
from backend.repositories.postgres_conversation_repo import PostgresConversationRepository
from backend.repositories.postgres_source_hash_repo import PostgresSourceHashRepository
from backend.strategies.cache.redis_semantic_cache import RedisSemanticCache
from backend.strategies.embedding.openai_embedding import OpenAIEmbedding
from backend.strategies.embedding.tf_sparse_encoder import TFSparseEncoder
from backend.strategies.llm.openai_llm import OpenAILLM
from backend.strategies.llm.openrouter_llm import OpenRouterLLM
from backend.strategies.reranker.cohere_reranker import CohereReranker
from backend.strategies.vectordb.qdrant_db import QdrantDB

logger = logging.getLogger(__name__)
app = FastAPI(title="kapa-rag query service")
app.include_router(admin_router)

_ALLOWED_ORIGINS = [
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    *[o.strip() for o in _os.getenv("EXTRA_ALLOWED_ORIGINS", "").split(",") if o.strip()],
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/metrics", include_in_schema=False)
def metrics() -> _PrometheusResponse:
    return _PrometheusResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.on_event("startup")
async def startup() -> None:
    from backend.logging import LogSetupFactory
    LogSetupFactory.create(settings.environment).configure("query")

    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=False)

    pool = await asyncpg.create_pool(settings.postgres_url.replace("+asyncpg", ""))
    app.state.db_pool = pool

    from backend.repositories.postgres_tenant_repo import PostgresTenantRepository
    app.state.tenant_repo = PostgresTenantRepository(pool)

    logger.info("query service started")
    cache = RedisSemanticCache()
    llm = OpenRouterLLM() if settings.llm_provider == "openrouter" else OpenAILLM()
    app.state.pipeline = QueryPipeline(
        llm=llm,
        embedder=OpenAIEmbedding(),
        sparse_encoder=TFSparseEncoder(),
        vector_db=QdrantDB(),
        reranker=CohereReranker(),
        cache=cache,
        conversation_repo=PostgresConversationRepository(pool),
        observers=[
            CacheObserver(cache, ttl_seconds=settings.cache_ttl_seconds),
            TraceObserver(),
            MetricsObserver(),
            UsageObserver(pool),
        ],
        source_hash_repo=PostgresSourceHashRepository(pool),
    )


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.db_pool.close()
    await app.state.redis.aclose()


# ── Request / Response models ─────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str
    conversation_id: UUID | None = None
    stream: bool = True


class QueryResponse(BaseModel):
    answer: str
    conversation_id: UUID
    source_urls: list[str]
    cached: bool


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.post("/query", dependencies=[Depends(rate_limit)])
async def handle_query(
    body: QueryRequest,
    tenant_id: str = Depends(get_tenant_id),
):
    """POST /query — stream=true returns SSE tokens, stream=false returns JSON."""
    if not body.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    conversation_id = body.conversation_id or uuid4()
    pipeline: QueryPipeline = app.state.pipeline

    if body.stream:
        return StreamingResponse(
            _sse_generator(pipeline, body.query, tenant_id, conversation_id),
            media_type="text/event-stream",
            headers={"X-Conversation-Id": str(conversation_id)},
        )

    result = await pipeline.handle(body.query, tenant_id, conversation_id)
    return QueryResponse(
        answer=result.answer,
        conversation_id=result.conversation_id,
        source_urls=list({c.source_url for c in result.source_chunks}),
        cached=result.cached,
    )


@app.delete("/query/conversation/{conversation_id}")
async def delete_conversation(
    conversation_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
) -> dict:
    """Clear conversation history for a given session."""
    pipeline: QueryPipeline = app.state.pipeline
    await pipeline._conversation_repo.delete_conversation(conversation_id)
    return {"deleted": str(conversation_id)}


@app.get("/query/conversations")
async def list_conversations(
    tenant_id: str = Depends(get_tenant_id),
) -> list[dict]:
    """List all conversations for this tenant, most recent first."""
    pipeline: QueryPipeline = app.state.pipeline
    return await pipeline._conversation_repo.list_conversations(tenant_id)


@app.get("/query/conversations/{conversation_id}/messages")
async def get_conversation_messages(
    conversation_id: UUID,
    tenant_id: str = Depends(get_tenant_id),
) -> list[dict]:
    """Return all messages for a conversation as [{role, content}]."""
    pipeline: QueryPipeline = app.state.pipeline
    return await pipeline._conversation_repo.get_messages(conversation_id, tenant_id)


@app.get("/usage")
async def get_usage(
    tenant_id: str = Depends(get_tenant_id),
    days: int = 30,
) -> dict:
    """Return token consumption and estimated cost for this tenant.

    Defaults to the last 30 days. Pass ?days=7 for a weekly view.
    Cache hits are excluded — only LLM calls are counted.
    """
    async with app.state.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT "
            "  COUNT(*)       AS total_queries, "
            "  SUM(tokens_in) AS total_in, "
            "  SUM(tokens_out) AS total_out, "
            "  SUM(cost_usd)  AS total_cost "
            "FROM usage_records "
            "WHERE tenant_id = $1 "
            "  AND created_at > NOW() - ($2 * INTERVAL '1 day')",
            UUID(tenant_id),
            days,
        )
    total_in  = int(row["total_in"]  or 0)
    total_out = int(row["total_out"] or 0)
    total_cost = Decimal(row["total_cost"] or 0)
    return {
        "tenant_id":     tenant_id,
        "period_days":   days,
        "total_queries": int(row["total_queries"] or 0),
        "tokens_in":     total_in,
        "tokens_out":    total_out,
        "tokens_total":  total_in + total_out,
        "cost_usd":      f"{total_cost:.8f}",
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


# ── SSE helper ────────────────────────────────────────────────────────────────

async def _sse_generator(
    pipeline: QueryPipeline,
    query: str,
    tenant_id: str,
    conversation_id: UUID,
):
    """Yields SSE-formatted token events, then a [DONE] sentinel."""
    try:
        async for token in pipeline.handle_stream(query, tenant_id, conversation_id):
            yield f"data: {json.dumps({'token': token})}\n\n"
        yield "data: [DONE]\n\n"
    except Exception as exc:
        yield f"data: {json.dumps({'error': str(exc)})}\n\n"
