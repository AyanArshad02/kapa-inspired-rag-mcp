"""
Integration tests for the ingestion pipeline.

Requires docker-compose services to be running:
  docker-compose up -d postgres qdrant

Run with:
  pytest tests/integration -m integration -v
"""
from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from qdrant_client import AsyncQdrantClient

from backend.connectors.base import ConnectorStrategy
from backend.connectors.factory import ConnectorFactory
from backend.core.ingestion_pipeline import IngestionPipeline
from backend.models import Chunk, IngestionJob, IngestionStatus, SourceType
from backend.repositories.postgres_ingestion_job_repo import PostgresIngestionJobRepository
from backend.strategies.base import EmbeddingStrategy, SparseEncoderStrategy
from backend.strategies.vectordb.qdrant_db import QdrantDB

pytestmark = pytest.mark.integration

_FAKE_DIM = 1536
_FAKE_VECTOR = [0.1] * _FAKE_DIM


# ── Fakes ─────────────────────────────────────────────────────────────────────

class _FakeEmbedder(EmbeddingStrategy):
    @property
    def dimension(self) -> int:
        return _FAKE_DIM

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_FAKE_VECTOR[:] for _ in texts]


class _FakeSparseEncoder(SparseEncoderStrategy):
    async def encode(self, texts: list[str]) -> list[tuple[list[int], list[float]]]:
        return [([1, 2, 3], [0.5, 0.3, 0.2]) for _ in texts]


class _FakeDocsConnector(ConnectorStrategy):
    """Yields pre-built chunks — no HTTP calls."""

    _N_CHUNKS = 5

    @property
    def source_type(self) -> SourceType:
        return SourceType.DOCS_SITE

    async def fetch_chunks(self, source_url: str, tenant_id: str) -> AsyncIterator[Chunk]:  # type: ignore[override]
        for i in range(self._N_CHUNKS):
            yield Chunk(
                tenant_id=tenant_id,
                source_url=source_url,
                source_type=SourceType.DOCS_SITE,
                content=f"Integration test chunk {i}: enough content to be meaningful and unique.",
                metadata={"chunk_index": i},
            )

    async def compute_content_hash(self, source_url: str) -> str:
        return "fake-hash-integration-test"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_pipeline(db_pool) -> tuple[IngestionPipeline, PostgresIngestionJobRepository]:
    repo = PostgresIngestionJobRepository(db_pool)
    factory = ConnectorFactory()
    factory.register(_FakeDocsConnector())

    pipeline = IngestionPipeline(
        connector_factory=factory,
        embedder=_FakeEmbedder(),
        sparse_encoder=_FakeSparseEncoder(),
        vector_db=QdrantDB(),
        job_repo=repo,
    )
    return pipeline, repo


async def _cleanup(db_pool, qdrant: AsyncQdrantClient, tenant_id: str, job_id) -> None:
    async with db_pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM ingestion_jobs WHERE tenant_id = $1", tenant_id
        )
    collection = f"tenant_{tenant_id}"
    # Use get_collections list — /exists endpoint not available in Qdrant <1.9
    result = await qdrant.get_collections()
    if collection in {c.name for c in result.collections}:
        await qdrant.delete_collection(collection)


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_pipeline_completes_and_chunks_appear_in_qdrant(
    db_pool, qdrant: AsyncQdrantClient, test_tenant_id: str
) -> None:
    pipeline, repo = _build_pipeline(db_pool)

    job = IngestionJob(
        tenant_id=test_tenant_id,
        source_url="https://docs.example.com/integration-test",
        source_type=SourceType.DOCS_SITE,
    )
    await repo.create(job)

    try:
        await pipeline.run(job)

        completed = await repo.get(job.id)
        assert completed is not None
        assert completed.status == IngestionStatus.COMPLETED
        assert completed.total_chunks == _FakeDocsConnector._N_CHUNKS

        collection = f"tenant_{test_tenant_id}"
        existing = {c.name for c in (await qdrant.get_collections()).collections}
        assert collection in existing
        count = await qdrant.count(collection)
        assert count.count == _FakeDocsConnector._N_CHUNKS

    finally:
        await _cleanup(db_pool, qdrant, test_tenant_id, job.id)


async def test_pipeline_marks_failed_on_connector_error(
    db_pool, qdrant: AsyncQdrantClient, test_tenant_id: str
) -> None:
    class _BrokenConnector(ConnectorStrategy):
        @property
        def source_type(self) -> SourceType:
            return SourceType.DOCS_SITE

        async def fetch_chunks(self, source_url: str, tenant_id: str) -> AsyncIterator[Chunk]:  # type: ignore[override]
            raise RuntimeError("simulated connector failure")
            yield  # make it a generator

        async def compute_content_hash(self, source_url: str) -> str:
            return ""

    repo = PostgresIngestionJobRepository(db_pool)
    factory = ConnectorFactory()
    factory.register(_BrokenConnector())

    pipeline = IngestionPipeline(
        connector_factory=factory,
        embedder=_FakeEmbedder(),
        sparse_encoder=_FakeSparseEncoder(),
        vector_db=QdrantDB(),
        job_repo=repo,
    )

    job = IngestionJob(
        tenant_id=test_tenant_id,
        source_url="https://docs.example.com/broken",
        source_type=SourceType.DOCS_SITE,
    )
    await repo.create(job)

    try:
        with pytest.raises(RuntimeError, match="simulated connector failure"):
            await pipeline.run(job)

        failed = await repo.get(job.id)
        assert failed is not None
        assert failed.status == IngestionStatus.FAILED
        assert "simulated connector failure" in (failed.error_message or "")

    finally:
        await _cleanup(db_pool, qdrant, test_tenant_id, job.id)


async def test_upsert_is_idempotent(
    db_pool, qdrant: AsyncQdrantClient, test_tenant_id: str
) -> None:
    """Running the same job twice must not double the chunk count."""
    pipeline, repo = _build_pipeline(db_pool)

    source_url = "https://docs.example.com/idempotent"

    job1 = IngestionJob(
        tenant_id=test_tenant_id,
        source_url=source_url,
        source_type=SourceType.DOCS_SITE,
    )
    job2 = IngestionJob(
        tenant_id=test_tenant_id,
        source_url=source_url,
        source_type=SourceType.DOCS_SITE,
    )
    await repo.create(job1)
    await repo.create(job2)

    try:
        await pipeline.run(job1)
        await pipeline.run(job2)

        collection = f"tenant_{test_tenant_id}"
        count = await qdrant.count(collection)
        assert count.count == _FakeDocsConnector._N_CHUNKS

    finally:
        await _cleanup(db_pool, qdrant, test_tenant_id, job1.id)






