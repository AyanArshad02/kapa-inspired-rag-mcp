from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from backend.connectors.factory import ConnectorFactory
from backend.models import IngestionJob, IngestionStatus, SourceType
from backend.repositories.base import IngestionJobRepository, SourceHashRepository
from backend.strategies.base import EmbeddingStrategy, SparseEncoderStrategy, VectorDBStrategy

logger = logging.getLogger(__name__)

_EMBED_BATCH_SIZE = 64


@dataclass
class RefreshResult:
    stale: bool
    job_id: str | None = None
    reason: str = ""


class FreshnessManager:
    """Detects stale sources and triggers the right re-ingestion strategy.

    Three operations:
    1. check_and_refresh  — polls a source, compares hash, enqueues a full
       re-ingestion job when the content has changed.
    2. handle_github_push — webhook path: re-index only the changed/added
       files, delete chunks for removed files. Much cheaper than full re-index.
    3. purge_source       — removes ALL chunks + the hash record for a source
       (used when a tenant deletes a PDF from the dashboard).
    """

    def __init__(
        self,
        connector_factory: ConnectorFactory,
        hash_repo: SourceHashRepository,
        job_repo: IngestionJobRepository,
        embedder: EmbeddingStrategy,
        sparse_encoder: SparseEncoderStrategy,
        vector_db: VectorDBStrategy,
    ) -> None:
        self._connectors = connector_factory
        self._hash_repo = hash_repo
        self._job_repo = job_repo
        self._embedder = embedder
        self._sparse_encoder = sparse_encoder
        self._vector_db = vector_db

    # ── Public API ─────────────────────────────────────────────────────────────

    async def check_and_refresh(
        self,
        tenant_id: str,
        source_url: str,
        source_type: SourceType,
    ) -> RefreshResult:
        """Check hash; if stale, create an ingestion job and enqueue it.

        Returns immediately — the actual re-ingestion runs asynchronously
        via Celery.
        """
        connector = self._connectors.get(source_type)
        new_hash = await connector.compute_content_hash(source_url)
        stored_hash = await self._hash_repo.get(tenant_id, source_url)

        if stored_hash == new_hash:
            return RefreshResult(stale=False, reason="hash_match")

        job = IngestionJob(
            tenant_id=tenant_id,
            source_url=source_url,
            source_type=source_type,
        )
        await self._job_repo.create(job)
        await self._enqueue_job(str(job.id))

        await self._hash_repo.upsert(tenant_id, source_url, new_hash, source_type.value)
        logger.info(
            "freshness: stale source tenant=%s url=%s job=%s", tenant_id, source_url, job.id
        )
        return RefreshResult(stale=True, job_id=str(job.id), reason="hash_changed")

    async def handle_github_push(
        self,
        tenant_id: str,
        repo_url: str,
        push_payload: dict[str, Any],
    ) -> None:
        """Process a GitHub push webhook for a single repo.

        Extracts changed/added/removed file paths from the payload and
        performs a surgical incremental update without touching unchanged files.
        """
        added: set[str] = set()
        modified: set[str] = set()
        removed: set[str] = set()

        for commit in push_payload.get("commits", []):
            added.update(commit.get("added", []))
            modified.update(commit.get("modified", []))
            removed.update(commit.get("removed", []))

        # Remove from Qdrant any chunks belonging to deleted/modified files
        # (modified files will be re-indexed with fresh content below)
        files_to_purge = removed | modified
        if files_to_purge:
            await asyncio.gather(
                *[
                    self._vector_db.delete_by_filter(
                        tenant_id, {"source_url": repo_url, "metadata.file_path": path}
                    )
                    for path in files_to_purge
                ]
            )
            logger.info(
                "freshness/webhook: purged %d file(s) tenant=%s repo=%s",
                len(files_to_purge),
                tenant_id,
                repo_url,
            )

        # Re-index added + modified files
        files_to_index = added | modified
        if files_to_index:
            await self._incremental_index(tenant_id, repo_url, files_to_index)

        # Update the repo-level content hash so the next scheduled poll
        # doesn't trigger a redundant full re-index.
        connector = self._connectors.get(SourceType.GITHUB)
        new_hash = await connector.compute_content_hash(repo_url)
        await self._hash_repo.upsert(tenant_id, repo_url, new_hash, SourceType.GITHUB.value)

    async def purge_source(self, tenant_id: str, source_url: str) -> None:
        """Hard-delete all chunks and the hash record for a source.

        Called when a tenant removes a PDF (or any source) from the dashboard.
        """
        await self._vector_db.delete_by_filter(tenant_id, {"source_url": source_url})
        await self._hash_repo.delete(tenant_id, source_url)
        logger.info("freshness: purged source tenant=%s url=%s", tenant_id, source_url)

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _incremental_index(
        self, tenant_id: str, repo_url: str, file_paths: set[str]
    ) -> None:
        """Fetch and embed only the given files from a GitHub repo."""
        from backend.connectors.github_connector import GitHubConnector

        connector = self._connectors.get(SourceType.GITHUB)
        if not isinstance(connector, GitHubConnector):
            logger.warning("incremental_index: connector is not GitHubConnector, skipping")
            return

        chunks = []
        async for chunk in connector.fetch_chunks(repo_url, tenant_id, file_filter=file_paths):
            chunks.append(chunk)
            if len(chunks) >= _EMBED_BATCH_SIZE:
                await self._embed_and_upsert(chunks)
                chunks.clear()

        if chunks:
            await self._embed_and_upsert(chunks)

        logger.info(
            "freshness/incremental: indexed %d file(s) tenant=%s repo=%s",
            len(file_paths),
            tenant_id,
            repo_url,
        )

    async def _embed_and_upsert(self, chunks) -> None:
        texts = [c.content for c in chunks]
        dense_vecs, sparse_pairs = await asyncio.gather(
            self._embedder.embed(texts),
            self._sparse_encoder.encode(texts),
        )
        for chunk, dense, (s_idx, s_val) in zip(chunks, dense_vecs, sparse_pairs):
            chunk.dense_vector = dense
            chunk.sparse_indices = s_idx
            chunk.sparse_values = s_val
        await self._vector_db.upsert(chunks)

    @staticmethod
    async def _enqueue_job(job_id: str) -> None:
        from backend.tasks.ingest import run_ingestion_job
        run_ingestion_job.delay(job_id)
