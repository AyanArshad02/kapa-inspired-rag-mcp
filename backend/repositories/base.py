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


class SourceHashRepository(ABC):
    """Stores the last-seen content hash per (tenant_id, source_url).

    Used by FreshnessManager to decide whether a source has changed
    since the last successful ingestion.
    """

    @abstractmethod
    async def get(self, tenant_id: str, source_url: str) -> str | None:
        """Return stored hash or None if this source has never been indexed."""
        ...

    @abstractmethod
    async def upsert(
        self, tenant_id: str, source_url: str, content_hash: str, source_type: str = "unknown"
    ) -> None:
        """Insert or update the hash for a (tenant_id, source_url) pair."""
        ...

    @abstractmethod
    async def delete(self, tenant_id: str, source_url: str) -> None:
        """Remove the hash record when a source is purged."""
        ...

    @abstractmethod
    async def list_by_tenant(self, tenant_id: str) -> list[dict]:
        """Return all source records for a tenant as dicts with source_url and source_type."""
        ...


class WebhookSecretRepository(ABC):
    """Stores per-tenant webhook secrets for GitHub push event verification.

    Each tenant gets a unique secret they register in their GitHub repo.
    Incoming webhook payloads are verified using HMAC-SHA256 with this secret.
    """

    @abstractmethod
    async def get(self, tenant_id: str) -> str | None:
        """Return the tenant's webhook secret, or None if not yet generated."""
        ...

    @abstractmethod
    async def upsert(self, tenant_id: str, secret: str) -> None:
        """Create or rotate the webhook secret for a tenant."""
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









