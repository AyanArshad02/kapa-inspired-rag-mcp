from __future__ import annotations

import hashlib
import os
import uuid

import asyncpg
import pytest
from qdrant_client import AsyncQdrantClient

_PG_URL = os.getenv(
    "TEST_POSTGRES_URL",
    "postgresql://kapa:kapa_dev_password@localhost:5432/kapa_rag",
)
_QDRANT_URL = os.getenv("TEST_QDRANT_URL", "http://localhost:6333")


@pytest.fixture
async def db_pool():
    pool = await asyncpg.create_pool(_PG_URL, min_size=1, max_size=3)
    yield pool
    await pool.close()


@pytest.fixture
def qdrant():
    return AsyncQdrantClient(url=_QDRANT_URL, check_compatibility=False)


@pytest.fixture
async def test_tenant_id(db_pool) -> str:
    """Insert a real tenant row and yield its UUID; delete on teardown."""
    tenant_id = str(uuid.uuid4())
    api_key_hash = hashlib.sha256(f"test-key-{tenant_id}".encode()).hexdigest()
    async with db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO tenants (tenant_id, name, api_key_hash) VALUES ($1, $2, $3)",
            tenant_id,
            "Integration Test Tenant",
            api_key_hash,
        )
    yield tenant_id
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM tenants WHERE tenant_id = $1", tenant_id)
