from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models import IngestionJob, IngestionStatus, SourceType

# ── helpers ────────────────────────────────────────────────────────────────────

def _make_freshness_manager(
    stored_hash: str | None = None,
    computed_hash: str = "abc123",
):
    """Build a FreshnessManager with all dependencies mocked."""
    from backend.core.freshness_manager import FreshnessManager

    mock_connector = AsyncMock()
    mock_connector.compute_content_hash = AsyncMock(return_value=computed_hash)
    mock_connector.source_type = SourceType.GITHUB

    factory = MagicMock()
    factory.get = MagicMock(return_value=mock_connector)

    hash_repo = AsyncMock()
    hash_repo.get = AsyncMock(return_value=stored_hash)
    hash_repo.upsert = AsyncMock()
    hash_repo.delete = AsyncMock()

    job = IngestionJob(
        tenant_id="t1",
        source_url="owner/repo",
        source_type=SourceType.GITHUB,
        status=IngestionStatus.PENDING,
    )
    job_repo = AsyncMock()
    job_repo.create = AsyncMock(return_value=job)
    job_repo.get = AsyncMock(return_value=job)

    embedder = AsyncMock()
    embedder.embed = AsyncMock(return_value=[[0.1] * 4])

    sparse_encoder = AsyncMock()
    sparse_encoder.encode = AsyncMock(return_value=[([0, 1], [0.5, 0.5])])

    vector_db = AsyncMock()
    vector_db.upsert = AsyncMock()
    vector_db.delete_by_filter = AsyncMock()

    fm = FreshnessManager(
        connector_factory=factory,
        hash_repo=hash_repo,
        job_repo=job_repo,
        embedder=embedder,
        sparse_encoder=sparse_encoder,
        vector_db=vector_db,
    )
    return fm, hash_repo, job_repo, vector_db, mock_connector


# ── check_and_refresh ──────────────────────────────────────────────────────────

class TestCheckAndRefresh:
    @pytest.mark.asyncio
    async def test_fresh_source_returns_not_stale(self):
        fm, hash_repo, job_repo, _, _ = _make_freshness_manager(
            stored_hash="abc123", computed_hash="abc123"
        )
        result = await fm.check_and_refresh("t1", "owner/repo", SourceType.GITHUB)

        assert result.stale is False
        assert result.job_id is None
        job_repo.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_stale_source_creates_job(self):
        fm, hash_repo, job_repo, _, _ = _make_freshness_manager(
            stored_hash="old_hash", computed_hash="new_hash"
        )
        with patch.object(fm, "_enqueue_job", new=AsyncMock()):
            result = await fm.check_and_refresh("t1", "owner/repo", SourceType.GITHUB)

        assert result.stale is True
        assert result.job_id is not None
        job_repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_stale_source_updates_hash(self):
        fm, hash_repo, _, _, _ = _make_freshness_manager(
            stored_hash="old_hash", computed_hash="new_hash"
        )
        with patch.object(fm, "_enqueue_job", new=AsyncMock()):
            await fm.check_and_refresh("t1", "owner/repo", SourceType.GITHUB)

        hash_repo.upsert.assert_called_once_with(
            "t1", "owner/repo", "new_hash", SourceType.GITHUB.value
        )

    @pytest.mark.asyncio
    async def test_first_time_source_triggers_job(self):
        fm, hash_repo, job_repo, _, _ = _make_freshness_manager(
            stored_hash=None, computed_hash="abc123"
        )
        with patch.object(fm, "_enqueue_job", new=AsyncMock()):
            result = await fm.check_and_refresh("t1", "owner/repo", SourceType.GITHUB)

        assert result.stale is True
        job_repo.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_hash_not_updated_when_source_is_fresh(self):
        fm, hash_repo, _, _, _ = _make_freshness_manager(
            stored_hash="same", computed_hash="same"
        )
        await fm.check_and_refresh("t1", "owner/repo", SourceType.GITHUB)
        hash_repo.upsert.assert_not_called()


# ── purge_source ───────────────────────────────────────────────────────────────

class TestPurgeSource:
    @pytest.mark.asyncio
    async def test_purge_calls_delete_by_filter(self):
        fm, hash_repo, _, vector_db, _ = _make_freshness_manager()
        await fm.purge_source("t1", "https://s3.example.com/report.pdf")

        vector_db.delete_by_filter.assert_called_once_with(
            "t1", {"source_url": "https://s3.example.com/report.pdf"}
        )

    @pytest.mark.asyncio
    async def test_purge_removes_hash_record(self):
        fm, hash_repo, _, _, _ = _make_freshness_manager()
        await fm.purge_source("t1", "https://s3.example.com/report.pdf")

        hash_repo.delete.assert_called_once_with("t1", "https://s3.example.com/report.pdf")


# ── handle_github_push ─────────────────────────────────────────────────────────

class TestHandleGithubPush:
    def _push_payload(
        self,
        added=None,
        modified=None,
        removed=None,
    ) -> dict:
        return {
            "commits": [
                {
                    "added": added or [],
                    "modified": modified or [],
                    "removed": removed or [],
                }
            ]
        }

    @pytest.mark.asyncio
    async def test_removed_files_trigger_delete(self):
        fm, _, _, vector_db, _ = _make_freshness_manager()

        with patch(
            "backend.connectors.github_connector.GitHubConnector",
        ):
            await fm.handle_github_push(
                "t1",
                "https://github.com/owner/repo",
                self._push_payload(removed=["src/old.py"]),
            )

        vector_db.delete_by_filter.assert_called()
        call_kwargs = vector_db.delete_by_filter.call_args_list[0][0]
        assert call_kwargs[0] == "t1"
        assert call_kwargs[1]["metadata.file_path"] == "src/old.py"

    @pytest.mark.asyncio
    async def test_no_changed_files_skips_delete(self):
        fm, _, _, vector_db, _ = _make_freshness_manager()
        await fm.handle_github_push(
            "t1", "https://github.com/owner/repo", self._push_payload()
        )
        vector_db.delete_by_filter.assert_not_called()

    @pytest.mark.asyncio
    async def test_hash_updated_after_push(self):
        fm, hash_repo, _, _, _ = _make_freshness_manager(computed_hash="new_commit_sha")
        await fm.handle_github_push(
            "t1", "https://github.com/owner/repo", self._push_payload()
        )
        hash_repo.upsert.assert_called_once_with(
            "t1", "https://github.com/owner/repo", "new_commit_sha", SourceType.GITHUB.value
        )
