from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.models import Chunk, ContextWindow, QueryResult, SourceType
from backend.observers.usage_observer import UsageObserver


def _make_context(tenant_id: str | None = None, tokens_in: int = 0, tokens_out: int = 0) -> ContextWindow:
    ctx = ContextWindow(
        query="What is DI?",
        chunks=[],
        total_tokens=tokens_in + tokens_out,
        tenant_id=tenant_id or str(uuid4()),
    )
    ctx.tokens_in = tokens_in
    ctx.tokens_out = tokens_out
    ctx.cost_usd = Decimal("0.001") if tokens_in > 0 else Decimal("0")
    return ctx


def _make_result(cached: bool = False) -> QueryResult:
    return QueryResult(
        answer="DI is a pattern.",
        source_chunks=[],
        conversation_id=uuid4(),
        cached=cached,
    )


def _mock_pool() -> MagicMock:
    mock_conn = AsyncMock()
    pool = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
    return pool, mock_conn


class TestUsageObserver:
    @pytest.mark.asyncio
    async def test_skips_cache_hit_zero_tokens(self):
        pool, mock_conn = _mock_pool()
        observer = UsageObserver(pool)
        ctx = _make_context(tokens_in=0, tokens_out=0)
        await observer.notify(ctx, _make_result(cached=True))
        mock_conn.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_records_llm_call_to_db(self):
        pool, mock_conn = _mock_pool()
        observer = UsageObserver(pool)
        ctx = _make_context(tokens_in=500, tokens_out=120)
        await observer.notify(ctx, _make_result(cached=False))
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_insert_contains_token_counts(self):
        pool, mock_conn = _mock_pool()
        observer = UsageObserver(pool)
        ctx = _make_context(tokens_in=300, tokens_out=80)
        result = _make_result()
        await observer.notify(ctx, result)
        call_args = mock_conn.execute.call_args
        # positional args after the SQL string are: tenant_id, conversation_id, tokens_in, tokens_out, cost_usd
        assert 300 in call_args.args
        assert 80 in call_args.args
