from __future__ import annotations

import json
from uuid import UUID

import redis.asyncio as aioredis

from backend.config import settings
from backend.models import Chunk, QueryResult, SourceType
from backend.strategies.base import CacheStrategy


class RedisCache(CacheStrategy):
    """Query result cache backed by Redis.

    Serialises QueryResult to JSON. Only answer text and source metadata
    are cached — dense vectors are not stored (no use after caching).
    """

    def __init__(self) -> None:
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=True)

    async def get(self, key: str) -> QueryResult | None:
        raw = await self._redis.get(key)
        if raw is None:
            return None
        return _deserialize(raw)

    async def set(self, key: str, result: QueryResult, ttl_seconds: int) -> None:
        await self._redis.setex(key, ttl_seconds, _serialize(result))

    async def invalidate(self, key: str) -> None:
        await self._redis.delete(key)

    async def close(self) -> None:
        await self._redis.aclose()


def _serialize(result: QueryResult) -> str:
    return json.dumps({
        "answer": result.answer,
        "conversation_id": str(result.conversation_id),
        "faithfulness_score": result.faithfulness_score,
        "cached": True,
        "source_chunks": [
            {
                "id": str(c.id),
                "content": c.content,
                "source_url": c.source_url,
                "source_type": c.source_type.value,
                "tenant_id": c.tenant_id,
            }
            for c in result.source_chunks
        ],
    })


def _deserialize(raw: str) -> QueryResult:
    data = json.loads(raw)
    chunks = [
        Chunk(
            id=UUID(c["id"]),
            content=c["content"],
            source_url=c["source_url"],
            source_type=SourceType(c["source_type"]),
            tenant_id=c["tenant_id"],
        )
        for c in data["source_chunks"]
    ]
    return QueryResult(
        answer=data["answer"],
        source_chunks=chunks,
        conversation_id=UUID(data["conversation_id"]),
        faithfulness_score=data.get("faithfulness_score"),
        cached=True,
    )
