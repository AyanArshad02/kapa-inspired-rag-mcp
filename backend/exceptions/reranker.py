from __future__ import annotations

from backend.exceptions.base import ErrorCode, KapaError


class RerankerError(KapaError):
    """Any failure originating from the reranker (Cohere, etc.)."""
    component = "reranker"


class RerankerFailedError(RerankerError):
    """Reranker API call failed (network error, API down, bad response).

    Retryable — transient provider issue.
    """
    error_code = ErrorCode.RERANKER_FAILED
    retryable = True


class RerankerTimeoutError(RerankerError):
    """Reranker API call timed out.

    Retryable — transient network hiccup.
    """
    error_code = ErrorCode.RERANKER_TIMEOUT
    retryable = True
