from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models import Chunk, SourceType


def _chunks(n: int) -> list[Chunk]:
    return [
        Chunk(
            tenant_id="t1",
            source_url=f"https://docs.example.com/page-{i}",
            source_type=SourceType.DOCS_SITE,
            content=f"Content of chunk {i}.",
        )
        for i in range(n)
    ]


class TestPassthroughReranker:
    async def test_returns_top_n(self):
        from backend.strategies.reranker.cohere_reranker import PassthroughReranker

        reranker = PassthroughReranker()
        chunks = _chunks(10)
        result = await reranker.rerank("any query", chunks, top_n=3)

        assert result == chunks[:3]

    async def test_returns_all_if_fewer_than_top_n(self):
        from backend.strategies.reranker.cohere_reranker import PassthroughReranker

        reranker = PassthroughReranker()
        chunks = _chunks(2)
        result = await reranker.rerank("any query", chunks, top_n=5)

        assert result == chunks

    async def test_empty_input_returns_empty(self):
        from backend.strategies.reranker.cohere_reranker import PassthroughReranker

        reranker = PassthroughReranker()
        result = await reranker.rerank("any query", [], top_n=5)
        assert result == []


class TestCohereReranker:
    async def test_returns_chunks_in_reranked_order(self):
        from backend.strategies.reranker.cohere_reranker import CohereReranker

        chunks = _chunks(5)

        # Cohere says: best order is chunk 3, chunk 1, chunk 0
        mock_result = MagicMock()
        mock_result.results = [
            MagicMock(index=3),
            MagicMock(index=1),
            MagicMock(index=0),
        ]

        with patch("backend.strategies.reranker.cohere_reranker.cohere.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_client.rerank = AsyncMock(return_value=mock_result)
            mock_cls.return_value = mock_client

            reranker = CohereReranker()
            result = await reranker.rerank("query", chunks, top_n=3)

        assert result[0] == chunks[3]
        assert result[1] == chunks[1]
        assert result[2] == chunks[0]

    async def test_empty_input_skips_api_call(self):
        from backend.strategies.reranker.cohere_reranker import CohereReranker

        with patch("backend.strategies.reranker.cohere_reranker.cohere.AsyncClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client

            reranker = CohereReranker()
            result = await reranker.rerank("query", [], top_n=5)

        assert result == []
        mock_client.rerank.assert_not_called()
