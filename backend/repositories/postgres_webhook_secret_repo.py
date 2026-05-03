from __future__ import annotations

import asyncpg

from backend.repositories.base import WebhookSecretRepository


class PostgresWebhookSecretRepository(WebhookSecretRepository):
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, tenant_id: str) -> str | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT secret FROM webhook_secrets WHERE tenant_id = $1",
                tenant_id,
            )
        return row["secret"] if row else None

    async def upsert(self, tenant_id: str, secret: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO webhook_secrets (tenant_id, secret)
                VALUES ($1, $2)
                ON CONFLICT (tenant_id)
                DO UPDATE SET secret = EXCLUDED.secret, updated_at = NOW()
                """,
                tenant_id,
                secret,
            )
