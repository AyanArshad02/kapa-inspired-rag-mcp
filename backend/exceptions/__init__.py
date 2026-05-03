"""Central import point for all application exceptions.

Usage anywhere in the codebase:
    from backend.exceptions import LLMTimeoutError, VectorDBConnectionError

Catching all application errors:
    from backend.exceptions import KapaError
    except KapaError as e:
        log error, increment Prometheus counter, etc.
"""
from backend.exceptions.base import ErrorCode, KapaError
from backend.exceptions.embedding import (
    EmbeddingBatchTooLargeError,
    EmbeddingError,
    EmbeddingFailedError,
)
from backend.exceptions.ingestion import IngestionError, ParseError, SourceUnreachableError
from backend.exceptions.llm import (
    LLMError,
    LLMInvalidResponseError,
    LLMRateLimitError,
    LLMTimeoutError,
)
from backend.exceptions.reranker import RerankerError, RerankerFailedError, RerankerTimeoutError
from backend.exceptions.storage import S3DeleteError, S3DownloadError, S3UploadError, StorageError
from backend.exceptions.vectordb import VectorDBConnectionError, VectorDBError, VectorDBQueryError

__all__ = [
    # Base
    "KapaError",
    "ErrorCode",
    # LLM
    "LLMError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMInvalidResponseError",
    # VectorDB
    "VectorDBError",
    "VectorDBConnectionError",
    "VectorDBQueryError",
    # Embedding
    "EmbeddingError",
    "EmbeddingFailedError",
    "EmbeddingBatchTooLargeError",
    # Reranker
    "RerankerError",
    "RerankerFailedError",
    "RerankerTimeoutError",
    # Ingestion
    "IngestionError",
    "SourceUnreachableError",
    "ParseError",
    # Storage
    "StorageError",
    "S3UploadError",
    "S3DownloadError",
    "S3DeleteError",
]
