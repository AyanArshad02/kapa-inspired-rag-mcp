from __future__ import annotations

import asyncio

import asyncpg

from backend.config import settings
from backend.connectors.docs_connector import DocsConnector
from backend.connectors.factory import ConnectorFactory
from backend.core.ingestion_pipeline import IngestionPipeline
from backend.strategies.embedding.openai_embedding import OpenAIEmbedding
from backend.strategies.embedding.tf_sparse_encoder import TFSparseEncoder
from backend.strategies.vectordb.qdrant_db import QdrantDB

_pool: asyncpg.Pool | None = None


async def get_db_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(settings.postgres_url.replace("+asyncpg", ""))
    return _pool


def build_ingestion_pipeline() -> IngestionPipeline:
    factory = ConnectorFactory()
    factory.register(DocsConnector())

    from backend.repositories.postgres_ingestion_job_repo import PostgresIngestionJobRepository

    pool = asyncio.run(_ensure_pool())

    return IngestionPipeline(
        connector_factory=factory,
        embedder=OpenAIEmbedding(),
        sparse_encoder=TFSparseEncoder(),
        vector_db=QdrantDB(),
        job_repo=PostgresIngestionJobRepository(pool),
    )


async def _ensure_pool() -> asyncpg.Pool:
    return await get_db_pool()










