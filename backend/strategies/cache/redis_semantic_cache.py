from __future__ import annotations

import json
import struct
from uuid import UUID, uuid4

import redis.asyncio as aioredis
from redis.commands.search.field import TagField, VectorField
from redis.commands.search.index_definition import IndexDefinition, IndexType
from redis.commands.search.query import Query

from backend.config import settings
from backend.models import Chunk, QueryResult, SourceType
from backend.strategies.base import SemanticCacheStrategy

_INDEX_NAME = "semcache_idx"
_KEY_PREFIX = "semcache:"
# cosine distance = 1 - similarity; threshold = 0.05 → similarity >= 0.95
_DISTANCE_THRESHOLD = 0.05


class RedisSemanticCache(SemanticCacheStrategy):
    """Semantic vector cache backed by Redis Stack (RediSearch HNSW + cosine).

    On get(): KNN-1 search filtered by tenant_id; returns a hit only when
    cosine distance ≤ 0.05 (i.e. similarity ≥ 0.95).
    On set(): stores the embedding + serialised result as a Redis HASH and
    attaches a TTL so stale answers expire automatically.
    """

    def __init__(self) -> None:
        self._redis = aioredis.from_url(settings.redis_url, decode_responses=False)
        self._index_ready = False

    async def _ensure_index(self) -> None:
        if self._index_ready:
            return
        try:
            await self._redis.ft(_INDEX_NAME).info()
        except Exception:
            await self._redis.ft(_INDEX_NAME).create_index(
                fields=[
                    TagField("tenant_id"),
                    VectorField(
                        "embedding",
                        "HNSW",
                        {
                            "TYPE": "FLOAT32",
                            "DIM": settings.openai_embedding_dimensions,
                            "DISTANCE_METRIC": "COSINE",
                        },
                    ),
                ],
                definition=IndexDefinition(
                    prefix=[_KEY_PREFIX], index_type=IndexType.HASH
                ),
            )
        self._index_ready = True

    async def get(self, embedding: list[float], tenant_id: str) -> QueryResult | None:
        await self._ensure_index()
        vec_bytes = _to_bytes(embedding)
        q = (
            Query(f"(@tenant_id:{{{tenant_id}}})=>[KNN 1 @embedding $vec AS score]")
            .sort_by("score")
            .return_fields("score", "payload")
            .dialect(2)
        )
        results = await self._redis.ft(_INDEX_NAME).search(
            q, query_params={"vec": vec_bytes}
        )
        if not results.docs:
            return None
        doc = results.docs[0]
        distance = float(doc.score)
        if distance > _DISTANCE_THRESHOLD:
            return None
        raw = doc.payload if isinstance(doc.payload, str) else doc.payload.decode()
        return _deserialize(raw)

    async def set(
        self,
        embedding: list[float],
        tenant_id: str,
        result: QueryResult,
        ttl_seconds: int,
    ) -> None:
        await self._ensure_index()
        key = f"{_KEY_PREFIX}{uuid4()}"
        await self._redis.hset(
            key,
            mapping={
                b"tenant_id": tenant_id.encode(),
                b"embedding": _to_bytes(embedding),
                b"payload": _serialize(result).encode(),
            },
        )
        await self._redis.expire(key, ttl_seconds)

    async def close(self) -> None:
        await self._redis.aclose()


def _to_bytes(embedding: list[float]) -> bytes:
    return struct.pack(f"{len(embedding)}f", *embedding)


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
