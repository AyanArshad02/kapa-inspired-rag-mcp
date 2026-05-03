from __future__ import annotations

from backend.exceptions.base import ErrorCode, KapaError


class LLMError(KapaError):
    """Any failure originating from the LLM provider (OpenAI, etc.)."""
    component = "llm"


class LLMTimeoutError(LLMError):
    """Request to the LLM provider timed out.

    Retryable — a transient network hiccup; worth one more attempt.
    """
    error_code = ErrorCode.LLM_TIMEOUT
    retryable = True


class LLMRateLimitError(LLMError):
    """LLM provider returned 429 (rate limited / quota exceeded).

    Retryable — back off and retry after the rate-limit window resets.
    """
    error_code = ErrorCode.LLM_RATE_LIMIT
    retryable = True


class LLMInvalidResponseError(LLMError):
    """LLM returned a response that could not be parsed or was empty.

    Not retryable — the same prompt will produce the same bad output.
    """
    error_code = ErrorCode.LLM_INVALID_RESPONSE
    retryable = False
