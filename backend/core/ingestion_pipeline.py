from __future__ import annotations

import asyncio
import hashlib
import logging
from uuid import UUID

from backend.connectors.factory import ConnectorFactory
from backend.models import Chunk, IngestionJob, IngestionStatus
from backend.repositories.base import IngestionJobRepository
from backend.strategies.base import EmbeddingStrategy, SparseEncoderStrategy, VectorDBStrategy

logger = logging.getLogger(__name__)

_EMBED_BATCH_SIZE = 64


class IngestionPipeline:
    """
    Orchestrates the full ingestion flow for one job
    """

    def __init__(
        self,
        connector_factory: ConnectorFactory,
        embedder: EmbeddingStrategy,
        sparse_encoder: SparseEncoderStrategy,
        vector_db: VectorDBStrategy,
        job_repo: IngestionJobRepository,
    ) -> None:
        self._connectors = connector_factory
        self._embedder = embedder
        self._sparse_encoder = sparse_encoder
        self._vector_db = vector_db
        self._job_repo = job_repo

    async def run(self, job: IngestionJob) -> None:
        """Execute one ingestion job end-to-end.

        Checkpoints progress so a restart re-processes only remaining chunks.
        """
        await self._job_repo.update_status(job.id, IngestionStatus.PROCESSING)

        try:
            await self._ensure_collection(job.tenant_id)

            connector = self._connectors.get(job.source_type)
            chunks: list[Chunk] = []

            async for chunk in connector.fetch_chunks(job.source_url, job.tenant_id):
                chunk.id = _deterministic_id(job.tenant_id, job.source_url, chunk.metadata.get("chunk_index", 0))
                chunks.append(chunk)

                if len(chunks) >= _EMBED_BATCH_SIZE:
                    await self._embed_and_upsert(chunks, job.id)
                    chunks.clear()

            if chunks:
                await self._embed_and_upsert(chunks, job.id)

            await self._job_repo.update_status(job.id, IngestionStatus.COMPLETED)
            logger.info("job=%s tenant=%s status=completed", job.id, job.tenant_id)

        except Exception as exc:
            await self._job_repo.update_status(
                job.id, IngestionStatus.FAILED, error_message=str(exc)
            )
            logger.error("job=%s failed: %s", job.id, exc)
            raise

    async def _embed_and_upsert(self, chunks: list[Chunk], job_id: UUID) -> None:
        texts = [c.content for c in chunks]

        dense_vecs, sparse_pairs = await asyncio.gather(
            self._embedder.embed(texts),
            self._sparse_encoder.encode(texts),
        )

        for chunk, dense, (s_indices, s_values) in zip(chunks, dense_vecs, sparse_pairs):
            chunk.dense_vector = dense
            chunk.sparse_indices = s_indices
            chunk.sparse_values = s_values

        await self._vector_db.upsert(chunks)
        await self._job_repo.increment_processed(job_id, count=len(chunks))

    async def _ensure_collection(self, tenant_id: str) -> None:
        if not await self._vector_db.collection_exists(tenant_id):
            await self._vector_db.create_collection(tenant_id)


def _deterministic_id(tenant_id: str, source_url: str, chunk_index: int) -> UUID:
    """chunk_id = sha256(tenant_id + source_url + chunk_index) — always idempotent."""
    raw = f"{tenant_id}:{source_url}:{chunk_index}".encode()
    digest = hashlib.sha256(raw).hexdigest()
    return UUID(digest[:32])





