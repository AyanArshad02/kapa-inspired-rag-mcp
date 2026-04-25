from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.models import Chunk, QueryResult, SourceType


def _make_result(answer: str = "Dependency injection is a pattern.") -> QueryResult:
    return QueryResult(
        answer=answer,
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


class TestSearchKnowledgeBase:
    async def test_returns_answer_with_sources(self):
        from backend.mcp.tools import search_knowledge_base_impl

        pipeline = MagicMock()
        pipeline.handle = AsyncMock(return_value=_make_result())

        output = await search_knowledge_base_impl(pipeline, "What is DI?", "tenant-1")

        assert "Dependency injection" in output
        assert "https://docs.example.com/di" in output
        assert "**Sources:**" in output

    async def test_cached_result_shows_cache_note(self):
        from backend.mcp.tools import search_knowledge_base_impl

        result = _make_result()
        result.cached = True
        pipeline = MagicMock()
        pipeline.handle = AsyncMock(return_value=result)

        output = await search_knowledge_base_impl(pipeline, "What is DI?", "tenant-1")

        assert "cache" in output.lower()

    async def test_deduplicates_source_urls(self):
        from backend.mcp.tools import search_knowledge_base_impl

        result = _make_result()
        # Add a duplicate source URL chunk
        dup = Chunk(
            tenant_id="t1",
            source_url="https://docs.example.com/di",
            source_type=SourceType.DOCS_SITE,
            content="Another chunk from the same page.",
        )
        result.source_chunks.append(dup)

        pipeline = MagicMock()
        pipeline.handle = AsyncMock(return_value=result)

        output = await search_knowledge_base_impl(pipeline, "What is DI?", "tenant-1")

        assert output.count("https://docs.example.com/di") == 1


class TestFetchAndQueryOnlineDocs:
    async def test_rejects_non_http_url(self):
        from backend.mcp.tools import fetch_and_query_online_docs_impl

        result = await fetch_and_query_online_docs_impl("file:///etc/passwd", "what is this?")
        # This is handled at the server layer, but tools.py shouldn't crash on odd input
        # The function will try to fetch — httpx will raise — we catch it
        assert isinstance(result, str)

    async def test_returns_answer_on_valid_html(self):
        from backend.mcp.tools import fetch_and_query_online_docs_impl

        html = """<html><body>
        <h1>FastAPI Tutorial</h1>
        <p>FastAPI is a modern Python web framework for building APIs.</p>
        <h2>Dependency Injection</h2>
        <p>Use Depends() to declare dependencies. FastAPI resolves them automatically.</p>
        </body></html>"""

        mock_response = MagicMock()
        mock_response.text = html
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        mock_result = _make_result("Use Depends() to declare dependencies.")

        with (
            patch("backend.mcp.tools.httpx.AsyncClient", return_value=mock_client),
            patch("backend.mcp.tools.OpenAIEmbedding") as mock_emb_cls,
            patch("backend.mcp.tools.OpenAILLM") as mock_llm_cls,
        ):
            mock_emb = AsyncMock()
            mock_emb.embed = AsyncMock(return_value=[[0.1] * 1536])
            mock_emb_cls.return_value = mock_emb

            mock_llm = AsyncMock()
            mock_llm.generate = AsyncMock(return_value=mock_result)
            mock_llm_cls.return_value = mock_llm

            output = await fetch_and_query_online_docs_impl(
                "https://fastapi.tiangolo.com/tutorial/",
                "How does dependency injection work?",
            )

        assert isinstance(output, str)
        assert len(output) > 0

    async def test_handles_fetch_error_gracefully(self):
        import httpx as _httpx

        from backend.mcp.tools import fetch_and_query_online_docs_impl

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(
            side_effect=_httpx.HTTPError("Connection refused")
        )

        with patch("backend.mcp.tools.httpx.AsyncClient", return_value=mock_client):
            output = await fetch_and_query_online_docs_impl(
                "https://unreachable.example.com/",
                "What is this?",
            )

        assert "Failed to fetch" in output
