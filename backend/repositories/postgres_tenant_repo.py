from __future__ import annotations

import hashlib

import asyncpg

from backend.repositories.base import TenantRepository


class PostgresTenantRepository(TenantRepository):
    """
    Validates API keys against the tenants table.

    API keys are stored as SHA-256 hashes, the raw key is never persisted.
    """

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_tenant_id_by_api_key(self, api_key: str) -> str | None:
        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT tenant_id FROM tenants WHERE api_key_hash = $1 AND is_active = TRUE",
                key_hash,
            )
        return str(row["tenant_id"]) if row else None

    async def tenant_exists(self, tenant_id: str) -> bool:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM tenants WHERE tenant_id = $1", tenant_id
            )
        return row is not None





