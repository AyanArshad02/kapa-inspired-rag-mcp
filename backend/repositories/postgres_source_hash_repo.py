from __future__ import annotations

import asyncpg

from backend.repositories.base import SourceHashRepository


class PostgresSourceHashRepository(SourceHashRepository):
    """Stores last-seen content hashes in the ``source_hashes`` table."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, tenant_id: str, source_url: str) -> str | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT content_hash FROM source_hashes WHERE tenant_id = $1 AND source_url = $2",
                tenant_id,
                source_url,
            )
        return row["content_hash"] if row else None

    async def upsert(
        self,
        tenant_id: str,
        source_url: str,
        content_hash: str,
        source_type: str = "unknown",
    ) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO source_hashes (tenant_id, source_url, source_type, content_hash)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (tenant_id, source_url)
                DO UPDATE SET
                    source_type  = EXCLUDED.source_type,
                    content_hash = EXCLUDED.content_hash,
                    updated_at   = NOW()
                """,
                tenant_id,
                source_url,
                source_type,
                content_hash,
            )

    async def delete(self, tenant_id: str, source_url: str) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM source_hashes WHERE tenant_id = $1 AND source_url = $2",
                tenant_id,
                source_url,
            )

    async def list_by_tenant(self, tenant_id: str) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT source_url, source_type FROM source_hashes WHERE tenant_id = $1 ORDER BY updated_at DESC",
                tenant_id,
            )
        return [{"source_url": r["source_url"], "source_type": r["source_type"]} for r in rows]
