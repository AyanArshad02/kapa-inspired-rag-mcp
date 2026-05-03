from __future__ import annotations

from backend.exceptions.base import ErrorCode, KapaError


class EmbeddingError(KapaError):
    """Any failure originating from the embedding model."""
    component = "embedding"


class EmbeddingFailedError(EmbeddingError):
    """The embedding API call failed (network error, API down, etc.).

    Retryable — transient provider issue.
    """
    error_code = ErrorCode.EMBEDDING_FAILED
    retryable = True


class EmbeddingBatchTooLargeError(EmbeddingError):
    """The batch of texts exceeded the provider's maximum input size.

    Not retryable — the batch must be split before retrying.
    The caller is responsible for chunking the input correctly.
    """
    error_code = ErrorCode.EMBEDDING_BATCH_TOO_LARGE
    retryable = False
