from __future__ import annotations

import base64
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.exceptions import ParseError
from backend.models import SourceType

# ── helpers ───────────────────────────────────────────────────────────────────

def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _mock_response(status: int, json_data: dict, headers: dict | None = None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data
    resp.headers = headers or {"X-RateLimit-Remaining": "500"}
    resp.raise_for_status = MagicMock()
    return resp


# ── _parse_repo_url ────────────────────────────────────────────────────────────

class TestParseRepoUrl:
    def test_https_url(self):
        from backend.connectors.github_connector import _parse_repo_url

        owner, repo = _parse_repo_url("https://github.com/anthropics/anthropic-sdk-python")
        assert owner == "anthropics"
        assert repo == "anthropic-sdk-python"

    def test_https_url_with_git_suffix(self):
        from backend.connectors.github_connector import _parse_repo_url

        owner, repo = _parse_repo_url("https://github.com/anthropics/anthropic-sdk-python.git")
        assert owner == "anthropics"
        assert repo == "anthropic-sdk-python"

    def test_short_form(self):
        from backend.connectors.github_connector import _parse_repo_url

        owner, repo = _parse_repo_url("anthropics/anthropic-sdk-python")
        assert owner == "anthropics"
        assert repo == "anthropic-sdk-python"

    def test_invalid_url_raises(self):
        from backend.connectors.github_connector import _parse_repo_url

        with pytest.raises(ParseError):
            _parse_repo_url("not-a-valid-url")


# ── _should_skip ──────────────────────────────────────────────────────────────

class TestShouldSkip:
    def test_keeps_python_file(self):
        from backend.connectors.github_connector import _should_skip

        assert _should_skip("backend/connectors/github_connector.py") is False

    def test_keeps_markdown_file(self):
        from backend.connectors.github_connector import _should_skip

        assert _should_skip("docs/README.md") is False

    def test_skips_node_modules(self):
        from backend.connectors.github_connector import _should_skip

        assert _should_skip("node_modules/lodash/index.js") is True

    def test_skips_pycache(self):
        from backend.connectors.github_connector import _should_skip

        assert _should_skip("backend/__pycache__/models.cpython-311.pyc") is True

    def test_skips_lock_file(self):
        from backend.connectors.github_connector import _should_skip

        assert _should_skip("package-lock.json") is True
        assert _should_skip("poetry.lock") is True

    def test_skips_unknown_extension(self):
        from backend.connectors.github_connector import _should_skip

        assert _should_skip("assets/logo.png") is True
        assert _should_skip("data/dump.sql") is True

    def test_skips_dist_dir(self):
        from backend.connectors.github_connector import _should_skip

        assert _should_skip("dist/bundle.js") is True


# ── GitHubConnector.source_type ───────────────────────────────────────────────

class TestGitHubConnectorSourceType:
    def test_source_type_is_github(self):
        from backend.connectors.github_connector import GitHubConnector

        assert GitHubConnector().source_type == SourceType.GITHUB


# ── GitHubConnector.fetch_chunks ──────────────────────────────────────────────

class TestFetchChunks:
    @pytest.mark.asyncio
    async def test_yields_chunks_for_python_file(self):
        from backend.connectors.github_connector import GitHubConnector

        tree_response = _mock_response(200, {
            "tree": [
                {"type": "blob", "path": "app.py", "size": 500},
            ]
        })

        python_src = "def hello():\n    return 'world'\n"
        file_response = _mock_response(200, {"content": _b64(python_src)})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[tree_response, file_response])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.connectors.github_connector.httpx.AsyncClient", return_value=mock_client):
            connector = GitHubConnector()
            chunks = [c async for c in connector.fetch_chunks("owner/myrepo", "tenant-1")]

        assert len(chunks) >= 1
        assert all(c.tenant_id == "tenant-1" for c in chunks)
        assert all(c.source_type == SourceType.GITHUB for c in chunks)
        assert all(c.source_url == "owner/myrepo" for c in chunks)

    @pytest.mark.asyncio
    async def test_skips_file_when_fetch_returns_none(self):
        from backend.connectors.github_connector import GitHubConnector

        tree_response = _mock_response(200, {
            "tree": [
                {"type": "blob", "path": "app.py", "size": 200},
            ]
        })
        not_found = _mock_response(404, {})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[tree_response, not_found])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.connectors.github_connector.httpx.AsyncClient", return_value=mock_client):
            connector = GitHubConnector()
            chunks = [c async for c in connector.fetch_chunks("owner/myrepo", "t1")]

        assert chunks == []

    @pytest.mark.asyncio
    async def test_file_metadata_attached_to_chunks(self):
        from backend.connectors.github_connector import GitHubConnector

        tree_response = _mock_response(200, {
            "tree": [
                {"type": "blob", "path": "src/utils.py", "size": 300},
            ]
        })
        python_src = "def add(a, b):\n    return a + b\n"
        file_response = _mock_response(200, {"content": _b64(python_src)})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[tree_response, file_response])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.connectors.github_connector.httpx.AsyncClient", return_value=mock_client):
            connector = GitHubConnector()
            chunks = [c async for c in connector.fetch_chunks("owner/myrepo", "t1")]

        assert len(chunks) >= 1
        assert chunks[0].metadata["file_path"] == "src/utils.py"
        assert chunks[0].metadata["repo"] == "owner/myrepo"

    @pytest.mark.asyncio
    async def test_oversized_files_are_skipped(self):
        from backend.connectors.github_connector import GitHubConnector

        tree_response = _mock_response(200, {
            "tree": [
                {"type": "blob", "path": "big_file.py", "size": 200_000},  # > 100KB
            ]
        })

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=tree_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.connectors.github_connector.httpx.AsyncClient", return_value=mock_client):
            connector = GitHubConnector()
            chunks = [c async for c in connector.fetch_chunks("owner/myrepo", "t1")]

        # Tree was fetched (1 call), no file fetch calls because file was filtered
        assert mock_client.get.call_count == 1
        assert chunks == []


# ── GitHubConnector.compute_content_hash ─────────────────────────────────────

class TestComputeContentHash:
    @pytest.mark.asyncio
    async def test_hash_uses_commit_sha(self):
        from backend.connectors.github_connector import GitHubConnector

        sha = "abc123def456"
        commit_response = _mock_response(200, {"sha": sha})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=commit_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("backend.connectors.github_connector.httpx.AsyncClient", return_value=mock_client):
            connector = GitHubConnector()
            h = await connector.compute_content_hash("owner/myrepo")

        expected = hashlib.sha256(sha.encode()).hexdigest()
        assert h == expected

    @pytest.mark.asyncio
    async def test_hash_falls_back_to_url_on_error(self):
        from backend.connectors.github_connector import GitHubConnector

        error_response = _mock_response(500, {})

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=error_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        url = "owner/myrepo"
        with patch("backend.connectors.github_connector.httpx.AsyncClient", return_value=mock_client):
            connector = GitHubConnector()
            h = await connector.compute_content_hash(url)

        expected = hashlib.sha256(url.encode()).hexdigest()
        assert h == expected
