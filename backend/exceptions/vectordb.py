from __future__ import annotations

from backend.exceptions.base import ErrorCode, KapaError


class VectorDBError(KapaError):
    """Any failure originating from the vector database (Qdrant, etc.)."""
    component = "vectordb"


class VectorDBConnectionError(VectorDBError):
    """Could not connect to the vector database.

    Retryable — the DB may be temporarily unreachable (restarting, overloaded).
    The circuit breaker will open after repeated failures.
    """
    error_code = ErrorCode.VECTORDB_CONNECTION
    retryable = True


class VectorDBQueryError(VectorDBError):
    """A search or upsert operation against the vector database failed.

    Not retryable — if the collection exists and the query is well-formed,
    retrying the identical operation is unlikely to succeed.
    """
    error_code = ErrorCode.VECTORDB_QUERY
    retryable = False
