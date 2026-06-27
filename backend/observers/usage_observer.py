from __future__ import annotations

from uuid import UUID

import asyncpg

from backend.models import ContextWindow, QueryResult
from backend.observers.base import QueryObserver


class UsageObserver(QueryObserver):
    """Persists per-query token usage to the usage_records table.

    Skips cache hits (tokens_in == 0) since no LLM call was made.
    Cost is whatever the LLM strategy calculated via PricingRegistry —
    this observer is completely model-agnostic.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def notify(self, context: ContextWindow, result: QueryResult) -> None:
        if context.tokens_in == 0 and context.tokens_out == 0:
            return  # cache hit — no LLM call, nothing to record

        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO usage_records "
                "(tenant_id, conversation_id, tokens_in, tokens_out, cost_usd) "
                "VALUES ($1, $2, $3, $4, $5)",
                UUID(context.tenant_id),
                result.conversation_id,
                context.tokens_in,
                context.tokens_out,
                context.cost_usd,
            )
