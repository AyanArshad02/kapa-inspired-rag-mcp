from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from backend.models import IngestionJob, IngestionStatus, Turn


class IngestionJobRepository(ABC):
    """Tracks ingestion job lifecycle.

    Status transitions (PENDING → PROCESSING → COMPLETED/FAILED) must be
    atomic — that's why this lives in PostgreSQL, not Redis.
    """

    @abstractmethod
    async def create(self, job: IngestionJob) -> IngestionJob:
        ...

    @abstractmethod
    async def get(self, job_id: UUID) -> IngestionJob | None:
        ...

    @abstractmethod
    async def update_status(
        self,
        job_id: UUID,
        status: IngestionStatus,
        error_message: str | None = None,
        checkpoint: dict | None = None,
    ) -> None:
        ...

    @abstractmethod
    async def increment_processed(self, job_id: UUID, count: int = 1) -> None:
        ...


class ConversationRepository(ABC):
    """Persists conversation turns for multi-turn context."""

    @abstractmethod
    async def save_turn(self, turn: Turn) -> Turn:
        ...

    @abstractmethod
    async def get_recent_turns(
        self, conversation_id: UUID, limit: int = 3
    ) -> list[Turn]:
        """Return the last `limit` turns, oldest first."""
        ...

    @abstractmethod
    async def delete_conversation(self, conversation_id: UUID) -> None:
        ...


class TenantRepository(ABC):
    """Source of truth for tenant identity and API key validation."""

    @abstractmethod
    async def get_tenant_id_by_api_key(self, api_key: str) -> str | None:
        """Return tenant_id or None if the key is invalid/revoked."""
        ...

    @abstractmethod
    async def tenant_exists(self, tenant_id: str) -> bool:
        ...









