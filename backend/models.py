from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


class IngestionStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceType(StrEnum):
    DOCS_SITE = "docs_site"
    GITHUB = "github"
    PDF = "pdf"
    SLACK = "slack"


@dataclass
class Chunk:
    """A single unit of indexed content.

    Carries both dense and sparse vectors so callers never have to
    re-embed after the fact.
    """

    id: UUID = field(default_factory=uuid4)
    tenant_id: str = ""
    source_type: SourceType = SourceType.DOCS_SITE
    source_url: str = ""
    content: str = ""
    dense_vector: list[float] = field(default_factory=list)
    sparse_indices: list[int] = field(default_factory=list)
    sparse_values: list[float] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    content_hash: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Turn:
    """One exchange in a conversation (user + assistant pair)."""

    id: UUID = field(default_factory=uuid4)
    conversation_id: UUID = field(default_factory=uuid4)
    tenant_id: str = ""
    user_message: str = ""
    assistant_message: str = ""
    source_chunk_ids: list[UUID] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class IngestionJob:
    """Tracks the lifecycle of a single ingestion request."""

    id: UUID = field(default_factory=uuid4)
    tenant_id: str = ""
    source_type: SourceType = SourceType.DOCS_SITE
    source_url: str = ""
    status: IngestionStatus = IngestionStatus.PENDING
    total_chunks: int = 0
    processed_chunks: int = 0
    error_message: str | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ContextWindow:
    """The assembled prompt context handed to the LLM.

    Token budget: system (~500) + chunks (~4000) + history (~600) + query (~500)
    = hard cap 6000 tokens enforced by ContextWindowBuilder.
    """

    query: str = ""
    chunks: list[Chunk] = field(default_factory=list)
    conversation_history: list[Turn] = field(default_factory=list)
    total_tokens: int = 0
    tenant_id: str = ""


@dataclass
class QueryResult:
    """The final response returned to the caller."""

    answer: str = ""
    source_chunks: list[Chunk] = field(default_factory=list)
    conversation_id: UUID = field(default_factory=uuid4)
    faithfulness_score: float | None = None
    cached: bool = False










