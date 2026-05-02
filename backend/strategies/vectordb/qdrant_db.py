from __future__ import annotations

from uuid import UUID

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    NamedSparseVector,
    NamedVector,
    PointStruct,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.exceptions import VectorDBConnectionError, VectorDBQueryError
from backend.models import Chunk, SourceType
from backend.strategies.base import VectorDBStrategy

_DENSE_VECTOR_NAME = "dense"
_SPARSE_VECTOR_NAME = "sparse"


class QdrantDB(VectorDBStrategy):
    """Qdrant self-hosted vector store.

    One collection per tenant: collection name = f"tenant_{tenant_id}".
    Hybrid search (dense + sparse) with RRF fusion is handled natively by Qdrant.
    """

    def __init__(self) -> None:
        self._client = AsyncQdrantClient(url=settings.qdrant_url, check_compatibility=False)
        self._dimension = settings.openai_embedding_dimensions
        self._circuit = CircuitBreaker("qdrant", failure_threshold=3, recovery_timeout=10.0)

    async def upsert(self, chunks: list[Chunk]) -> None:
        if not chunks:
            return
        tenant_id = chunks[0].tenant_id
        points = [_chunk_to_point(c) for c in chunks]
        try:
            await self._circuit.call(
                self._client.upsert,
                collection_name=_collection(tenant_id),
                points=points,
            )
        except CircuitOpenError as exc:
            raise VectorDBConnectionError("Qdrant circuit open") from exc
        except Exception as exc:
            raise _classify_qdrant_error(exc) from exc

    async def hybrid_search(
        self,
        tenant_id: str,
        dense_vector: list[float],
        sparse_indices: list[int],
        sparse_values: list[float],
        top_k: int = 20,
    ) -> list[Chunk]:
        from qdrant_client.models import FusionQuery, Fusion, Prefetch

        try:
            results = await self._circuit.call(
                self._client.query_points,
                collection_name=_collection(tenant_id),
                prefetch=[
                    Prefetch(query=dense_vector, using=_DENSE_VECTOR_NAME, limit=top_k),
                    Prefetch(
                        query=SparseVector(indices=sparse_indices, values=sparse_values),
                        using=_SPARSE_VECTOR_NAME,
                        limit=top_k,
                    ),
                ],
                query=FusionQuery(fusion=Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )
        except CircuitOpenError as exc:
            raise VectorDBConnectionError("Qdrant circuit open") from exc
        except Exception as exc:
            raise _classify_qdrant_error(exc) from exc

        return [_point_to_chunk(r) for r in results.points]

    async def delete_chunks(self, tenant_id: str, chunk_ids: list[str]) -> None:
        from qdrant_client.models import PointIdsList

        try:
            await self._circuit.call(
                self._client.delete,
                collection_name=_collection(tenant_id),
                points_selector=PointIdsList(points=chunk_ids),
            )
        except CircuitOpenError as exc:
            raise VectorDBConnectionError("Qdrant circuit open") from exc
        except Exception as exc:
            raise _classify_qdrant_error(exc) from exc

    async def delete_by_filter(self, tenant_id: str, filter_dict: dict[str, str]) -> None:
        from qdrant_client.models import FilterSelector

        conditions = [
            FieldCondition(key=k, match=MatchValue(value=v))
            for k, v in filter_dict.items()
        ]
        try:
            await self._circuit.call(
                self._client.delete,
                collection_name=_collection(tenant_id),
                points_selector=FilterSelector(filter=Filter(must=conditions)),
            )
        except CircuitOpenError as exc:
            raise VectorDBConnectionError("Qdrant circuit open") from exc
        except Exception as exc:
            raise _classify_qdrant_error(exc) from exc

    async def collection_exists(self, tenant_id: str) -> bool:
        # Avoid /collections/{name}/exists which was added post-1.7.4
        try:
            result = await self._client.get_collections()
        except Exception as exc:
            raise VectorDBConnectionError(str(exc)) from exc
        return _collection(tenant_id) in {c.name for c in result.collections}

    async def create_collection(self, tenant_id: str) -> None:
        try:
            await self._client.create_collection(
                collection_name=_collection(tenant_id),
                vectors_config={
                    _DENSE_VECTOR_NAME: VectorParams(
                        size=self._dimension,
                        distance=Distance.COSINE,
                    ),
                },
                sparse_vectors_config={
                    _SPARSE_VECTOR_NAME: SparseVectorParams(
                        index=SparseIndexParams(on_disk=False)
                    ),
                },
            )
        except Exception as exc:
            raise VectorDBConnectionError(str(exc)) from exc


def _classify_qdrant_error(exc: Exception) -> VectorDBConnectionError | VectorDBQueryError:
    """Map raw Qdrant / httpx exceptions to our typed hierarchy."""
    name = type(exc).__name__
    if any(t in name for t in ("Connect", "Timeout", "Network", "Connection", "Unavailable")):
        return VectorDBConnectionError(str(exc))
    return VectorDBQueryError(str(exc))


def _collection(tenant_id: str) -> str:
    return f"tenant_{tenant_id}"


def _chunk_to_point(chunk: Chunk) -> PointStruct:
    return PointStruct(
        id=str(chunk.id),
        vector={
            _DENSE_VECTOR_NAME: chunk.dense_vector,
            _SPARSE_VECTOR_NAME: SparseVector(
                indices=chunk.sparse_indices,
                values=chunk.sparse_values,
            ),
        },
        payload={
            "tenant_id": chunk.tenant_id,
            "content": chunk.content,
            "source_url": chunk.source_url,
            "source_type": chunk.source_type.value,
            "content_hash": chunk.content_hash,
            "metadata": chunk.metadata,
        },
    )


def _point_to_chunk(point) -> Chunk:
    p = point.payload
    return Chunk(
        id=UUID(point.id),
        tenant_id=p["tenant_id"],
        content=p["content"],
        source_url=p["source_url"],
        source_type=SourceType(p["source_type"]),
        content_hash=p.get("content_hash", ""),
        metadata=p.get("metadata", {}),
    )




