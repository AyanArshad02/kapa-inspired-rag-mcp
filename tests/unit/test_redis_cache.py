from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

from backend.models import Chunk, QueryResult, SourceType
from backend.strategies.cache.redis_cache import _deserialize, _serialize


def _make_result() -> QueryResult:
    return QueryResult(
        answer="Dependency injection is a pattern.",
        source_chunks=[
            Chunk(
                tenant_id="t1",
                source_url="https://docs.example.com/di",
                source_type=SourceType.DOCS_SITE,
                content="DI lets you declare shared logic.",
            )
        ],
        conversation_id=uuid4(),
        cached=False,
    )


class TestSerialization:
    def test_round_trip_preserves_answer(self):
        result = _make_result()
        restored = _deserialize(_serialize(result))
        assert restored.answer == result.answer

    def test_round_trip_preserves_source_url(self):
        result = _make_result()
        restored = _deserialize(_serialize(result))
        assert restored.source_chunks[0].source_url == result.source_chunks[0].source_url

    def test_cached_flag_is_true_after_deserialize(self):
        result = _make_result()
        result.cached = False
        restored = _deserialize(_serialize(result))
        assert restored.cached is True   # always True when read from cache

    def test_conversation_id_preserved(self):
        result = _make_result()
        restored = _deserialize(_serialize(result))
        assert restored.conversation_id == result.conversation_id


class TestRedisCache:
    async def test_get_returns_none_on_miss(self):
        with patch("backend.strategies.cache.redis_cache.aioredis.from_url") as mock_url:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_url.return_value = mock_redis

            from backend.strategies.cache.redis_cache import RedisCache
            cache = RedisCache()
            result = await cache.get("missing-key")

        assert result is None

    async def test_get_returns_result_on_hit(self):
        original = _make_result()
        serialized = _serialize(original)

        with patch("backend.strategies.cache.redis_cache.aioredis.from_url") as mock_url:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=serialized)
            mock_url.return_value = mock_redis

            from backend.strategies.cache.redis_cache import RedisCache
            cache = RedisCache()
            result = await cache.get("some-key")

        assert result is not None
        assert result.answer == original.answer

    async def test_set_calls_setex_with_ttl(self):
        result = _make_result()

        with patch("backend.strategies.cache.redis_cache.aioredis.from_url") as mock_url:
            mock_redis = AsyncMock()
            mock_url.return_value = mock_redis

            from backend.strategies.cache.redis_cache import RedisCache
            cache = RedisCache()
            await cache.set("key", result, ttl_seconds=300)

        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args[0]
        assert call_args[0] == "key"
        assert call_args[1] == 300
