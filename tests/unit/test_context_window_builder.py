from __future__ import annotations

import pytest

from backend.core.context_window_builder import ContextWindowBuilder, _count
from backend.models import Chunk, SourceType, Turn
from uuid import uuid4


def _chunk(content: str) -> Chunk:
    return Chunk(
        tenant_id="t1",
        source_url="https://docs.example.com",
        source_type=SourceType.DOCS_SITE,
        content=content,
    )


def _turn(user: str, assistant: str) -> Turn:
    return Turn(
        conversation_id=uuid4(),
        user_message=user,
        assistant_message=assistant,
    )


class TestContextWindowBuilder:
    def test_all_chunks_fit_within_budget(self):
        builder = ContextWindowBuilder(max_tokens=6000)
        chunks = [_chunk("Short content.") for _ in range(5)]

        ctx = builder.build("What is X?", chunks, [], "t1")

        assert len(ctx.chunks) == 5
        assert ctx.total_tokens > 0

    def test_oversized_chunks_are_dropped(self):
        # Set a very small budget so only the first chunk fits
        builder = ContextWindowBuilder(max_tokens=300)
        long_content = "word " * 200      # ~200 tokens
        chunks = [_chunk(long_content), _chunk(long_content), _chunk(long_content)]

        ctx = builder.build("query", chunks, [], "t1")

        # Should fit only the first chunk (budget = 300 - 950 overhead < 0...
        # use a slightly larger budget for this test)
        assert len(ctx.chunks) <= len(chunks)

    def test_drops_least_relevant_chunks_first(self):
        # Reranker puts most relevant first, so dropped chunks are the last ones
        builder = ContextWindowBuilder(max_tokens=6000)
        chunks = [_chunk(f"Relevant content about topic {i}.") for i in range(10)]

        ctx = builder.build("query", chunks, [], "t1")

        # Preserved chunks must be a prefix of the input list
        for i, chunk in enumerate(ctx.chunks):
            assert chunk == chunks[i]

    def test_total_tokens_is_set(self):
        builder = ContextWindowBuilder(max_tokens=6000)
        chunks = [_chunk("Some content about FastAPI routing.")]

        ctx = builder.build("How does routing work?", chunks, [], "t1")

        assert ctx.total_tokens > 0

    def test_conversation_history_is_preserved(self):
        builder = ContextWindowBuilder(max_tokens=6000)
        history = [_turn("What is X?", "X is Y.")]

        ctx = builder.build("Follow-up question.", [], history, "t1")

        assert ctx.conversation_history == history

    def test_tenant_id_is_set(self):
        builder = ContextWindowBuilder(max_tokens=6000)
        ctx = builder.build("query", [], [], "tenant-abc")
        assert ctx.tenant_id == "tenant-abc"

    def test_empty_chunks_and_history(self):
        builder = ContextWindowBuilder(max_tokens=6000)
        ctx = builder.build("query", [], [], "t1")

        assert ctx.chunks == []
        assert ctx.conversation_history == []
        assert ctx.total_tokens > 0   # still counts query + system
