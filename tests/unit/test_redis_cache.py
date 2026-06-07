from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.models import Chunk, QueryResult, SourceType
from backend.strategies.cache.redis_semantic_cache import _deserialize, _serialize


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


def _fake_embedding(dim: int = 8) -> list[float]:
    return [0.1] * dim


class TestSerialization:
    def test_round_trip_preserves_answer(self):
        result = _make_result()
        assert _deserialize(_serialize(result)).answer == result.answer

    def test_round_trip_preserves_source_url(self):
        result = _make_result()
        restored = _deserialize(_serialize(result))
        assert restored.source_chunks[0].source_url == result.source_chunks[0].source_url

    def test_cached_flag_is_true_after_deserialize(self):
        result = _make_result()
        result.cached = False
        assert _deserialize(_serialize(result)).cached is True

    def test_conversation_id_preserved(self):
        result = _make_result()
        assert _deserialize(_serialize(result)).conversation_id == result.conversation_id


class TestRedisSemanticCache:
    def _make_cache(self):
        """Return a RedisSemanticCache with a mocked Redis client."""
        with patch(
            "backend.strategies.cache.redis_semantic_cache.aioredis.from_url"
        ) as mock_url:
            mock_redis = AsyncMock()
            mock_url.return_value = mock_redis
            from backend.strategies.cache.redis_semantic_cache import RedisSemanticCache
            cache = RedisSemanticCache()
            cache._index_ready = True  # skip index creation
            return cache, mock_redis

    @pytest.mark.asyncio
    async def test_get_returns_none_when_no_docs(self):
        cache, mock_redis = self._make_cache()
        ft_mock = AsyncMock()
        ft_mock.search = AsyncMock(return_value=MagicMock(docs=[]))
        mock_redis.ft = MagicMock(return_value=ft_mock)

        result = await cache.get(_fake_embedding(), "tenant1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_none_when_distance_too_large(self):
        cache, mock_redis = self._make_cache()
        original = _make_result()
        doc = MagicMock()
        doc.score = "0.2"  # distance > 0.10 → miss
        doc.payload = _serialize(original)
        ft_mock = AsyncMock()
        ft_mock.search = AsyncMock(return_value=MagicMock(docs=[doc]))
        mock_redis.ft = MagicMock(return_value=ft_mock)

        result = await cache.get(_fake_embedding(), "tenant1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_returns_result_on_hit(self):
        cache, mock_redis = self._make_cache()
        original = _make_result()
        doc = MagicMock()
        doc.score = "0.01"  # distance ≤ 0.10 → hit
        doc.result_json = _serialize(original)
        ft_mock = AsyncMock()
        ft_mock.search = AsyncMock(return_value=MagicMock(docs=[doc]))
        mock_redis.ft = MagicMock(return_value=ft_mock)

        result = await cache.get(_fake_embedding(), "tenant1")
        assert result is not None
        assert result.answer == original.answer
        assert result.cached is True

    @pytest.mark.asyncio
    async def test_set_calls_hset_and_expire(self):
        cache, mock_redis = self._make_cache()
        result = _make_result()

        await cache.set(_fake_embedding(), "tenant1", result, ttl_seconds=300)

        mock_redis.hset.assert_called_once()
        mock_redis.expire.assert_called_once()
        _, expire_ttl = mock_redis.expire.call_args[0]
        assert expire_ttl == 300
