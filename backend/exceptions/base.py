"""Base exception class and ErrorCode enum for the entire application.

Every exception in this codebase inherits from KapaError.
The three class-level fields (error_code, component, retryable) must be
set on every concrete (leaf) exception class — they drive Prometheus labels,
structured log fields, and circuit-breaker retry decisions.

Hierarchy contract:
  KapaError               ← base, retryable=False by default
  └── CategoryError       ← sets component (e.g. "llm", "vectordb")
      └── LeafError       ← sets error_code + optionally retryable=True
"""
from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    # ── LLM ──────────────────────────────────────────────────────────────────
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_RATE_LIMIT = "LLM_RATE_LIMIT"
    LLM_INVALID_RESPONSE = "LLM_INVALID_RESPONSE"

    # ── Vector DB ─────────────────────────────────────────────────────────────
    VECTORDB_CONNECTION = "VECTORDB_CONNECTION"
    VECTORDB_QUERY = "VECTORDB_QUERY"

    # ── Embedding ─────────────────────────────────────────────────────────────
    EMBEDDING_FAILED = "EMBEDDING_FAILED"
    EMBEDDING_BATCH_TOO_LARGE = "EMBEDDING_BATCH_TOO_LARGE"

    # ── Reranker ──────────────────────────────────────────────────────────────
    RERANKER_FAILED = "RERANKER_FAILED"
    RERANKER_TIMEOUT = "RERANKER_TIMEOUT"

    # ── Ingestion ─────────────────────────────────────────────────────────────
    SOURCE_UNREACHABLE = "SOURCE_UNREACHABLE"
    PARSE_ERROR = "PARSE_ERROR"

    # ── Storage ───────────────────────────────────────────────────────────────
    S3_UPLOAD_FAILED = "S3_UPLOAD_FAILED"
    S3_DOWNLOAD_FAILED = "S3_DOWNLOAD_FAILED"
    S3_DELETE_FAILED = "S3_DELETE_FAILED"


class KapaError(Exception):
    """Base for all application errors.

    Subclasses set class-level attributes:
      error_code  — identifies the specific failure (drives Prometheus labels)
      component   — which subsystem failed (drives Prometheus labels + log fields)
      retryable   — True means the circuit breaker should wait-and-retry;
                    False means fail immediately (retrying won't help)

    Usage:
        raise LLMTimeoutError("OpenAI timed out after 30s", cause=original_exc)

    Catching:
        except KapaError as e:
            rag_errors_total.labels(
                component=e.component,
                error_type=type(e).__name__,
            ).inc()
    """

    error_code: ErrorCode
    component: str
    retryable: bool = False

    def __init__(self, message: str, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause

    def __str__(self) -> str:
        if self.cause:
            return f"{self.message} | caused by: {type(self.cause).__name__}: {self.cause}"
        return self.message

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}("
            f"message={self.message!r}, "
            f"component={getattr(self, 'component', '?')!r}, "
            f"retryable={getattr(self, 'retryable', False)}"
            f")"
        )
