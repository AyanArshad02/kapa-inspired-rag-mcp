from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models import Chunk, ContextWindow, SourceType


def _make_context(total_tokens: int = 100, n_chunks: int = 2) -> ContextWindow:
    chunks = [
        Chunk(
            tenant_id="t1",
            source_url="https://docs.example.com/page",
            source_type=SourceType.DOCS_SITE,
            content=f"Chunk content number {i}.",
        )
        for i in range(n_chunks)
    ]
    return ContextWindow(
        query="What is dependency injection?",
        chunks=chunks,
        conversation_history=[],
        total_tokens=total_tokens,
        tenant_id="t1",
    )


@pytest.fixture
def mock_openai():
    with patch("backend.strategies.llm.openai_llm.AsyncOpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        yield mock_client


class TestOpenAILLM:
    def test_selects_fast_model_for_small_context(self, mock_openai):
        from backend.strategies.llm.openai_llm import _select_model

        ctx = _make_context(total_tokens=200)   # below fast threshold (500)
        from backend.config import settings
        assert _select_model(ctx) == settings.llm_fast_model

    def test_selects_default_model_for_large_context(self, mock_openai):
        from backend.strategies.llm.openai_llm import _select_model

        ctx = _make_context(total_tokens=800)   # above fast threshold (500)
        from backend.config import settings
        assert _select_model(ctx) == settings.llm_default_model

    def test_build_messages_includes_system_and_query(self):
        from backend.strategies.llm._prompts import build_messages

        ctx = _make_context()
        messages = build_messages(ctx)

        roles = [m["role"] for m in messages]
        assert roles[0] == "system"
        assert roles[-1] == "user"
        assert ctx.query in messages[-1]["content"]

    def test_build_messages_includes_chunk_sources(self):
        from backend.strategies.llm._prompts import build_messages

        ctx = _make_context()
        messages = build_messages(ctx)
        last_msg = messages[-1]["content"]

        for chunk in ctx.chunks:
            assert chunk.source_url in last_msg
            assert chunk.content in last_msg

    def test_build_messages_includes_conversation_history(self):
        from uuid import uuid4

        from backend.models import Turn
        from backend.strategies.llm._prompts import build_messages
        ctx = _make_context()
        conv_id = uuid4()
        ctx.conversation_history = [
            Turn(
                conversation_id=conv_id,
                user_message="Previous question",
                assistant_message="Previous answer",
            )
        ]

        messages = build_messages(ctx)
        roles = [m["role"] for m in messages]
        assert "user" in roles
        assert "assistant" in roles
        user_msgs = [m["content"] for m in messages if m["role"] == "user"]
        assert any("Previous question" in m for m in user_msgs)

    async def test_generate_returns_query_result(self, mock_openai):
        from backend.strategies.llm.openai_llm import OpenAILLM

        mock_choice = MagicMock()
        mock_choice.message.content = "Dependency injection lets you declare shared logic."
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_openai.chat.completions.create = AsyncMock(return_value=mock_response)

        llm = OpenAILLM()
        llm._circuit.call = AsyncMock(return_value=mock_response)

        ctx = _make_context()
        result = await llm.generate(ctx)

        assert result.answer == "Dependency injection lets you declare shared logic."
        assert result.source_chunks == ctx.chunks
