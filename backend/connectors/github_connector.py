from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import time
from collections.abc import AsyncIterator
from urllib.parse import urlparse

import httpx

from backend.config import settings
from backend.connectors.base import ConnectorStrategy
from backend.connectors.chunkers.code_block_aware_chunker import CodeBlockAwareChunker
from backend.exceptions import ParseError, SourceUnreachableError
from backend.models import Chunk, SourceType
from backend.strategies.base import ChunkerStrategy

logger = logging.getLogger(__name__)

# Files we never want to index
_SKIP_DIRS = {
    "node_modules", "__pycache__", ".git", "dist", "build",
    ".venv", "venv", ".mypy_cache", ".pytest_cache", "coverage",
    "vendor", "third_party",
}

_SKIP_FILENAMES = {
    "package-lock.json", "yarn.lock", "poetry.lock", "Pipfile.lock",
    "pnpm-lock.yaml", "composer.lock", "Gemfile.lock",
}

_INDEXABLE_EXTS = {
    ".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".kt",
    ".rs", ".rb", ".php", ".md", ".mdx", ".rst", ".txt",
}

_MAX_FILE_BYTES = 100_000   # skip files > 100 KB (likely generated/minified)
_REQUEST_DELAY  = 0.12      # 120ms between requests → ~500 files/minute
_RATE_LIMIT_BUFFER = 10     # pause if remaining requests drop below this


class GitHubConnector(ConnectorStrategy):
    """
    Fetches source files from a public or private GitHub repository and
    yields chunks using CodeBlockAwareChunker.

    Flow:
      1. Parse owner/repo from URL
      2. Fetch full file tree in one API call
      3. Filter to indexable files
      4. Fetch each file content (with rate-limit awareness)
      5. Chunk with CodeBlockAwareChunker and yield
    """

    def __init__(self, chunker: ChunkerStrategy | None = None) -> None:
        self._chunker = chunker or CodeBlockAwareChunker()
        self._headers = _build_headers()

    @property
    def source_type(self) -> SourceType:
        return SourceType.GITHUB

    async def fetch_chunks(
        self,
        source_url: str,
        tenant_id: str,
        file_filter: set[str] | None = None,
    ) -> AsyncIterator[Chunk]:
        """Yield chunks for all indexable files in the repo.

        When ``file_filter`` is provided (e.g. from a webhook payload),
        only the listed file paths are fetched — skipping the full tree walk.
        """
        owner, repo = _parse_repo_url(source_url)
        logger.info("github connector: %s/%s", owner, repo)

        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            headers=self._headers,
            timeout=30,
            follow_redirects=True,
        ) as client:
            if file_filter is not None:
                paths = [p for p in file_filter if not _should_skip(p)]
            else:
                paths = await _list_indexable_files(client, owner, repo)
            logger.info("github connector: %d indexable files", len(paths))

            for path in paths:
                content = await _fetch_file(client, owner, repo, path)
                if content is None:
                    continue

                metadata = {
                    "tenant_id": tenant_id,
                    "source_url": source_url,
                    "source_type": SourceType.GITHUB.value,
                    "file_path": path,
                    "repo": f"{owner}/{repo}",
                }
                for chunk in self._chunker.chunk(content, {**metadata, "source_url": path}):
                    # Restore the repo URL as source_url for citation purposes
                    chunk.source_url = source_url
                    chunk.metadata["file_path"] = path
                    yield chunk

    async def compute_content_hash(self, source_url: str) -> str:
        """Hash = SHA-256 of the latest commit SHA — changes when repo is updated."""
        owner, repo = _parse_repo_url(source_url)
        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            headers=self._headers,
            timeout=15,
        ) as client:
            resp = await client.get(f"/repos/{owner}/{repo}/commits/HEAD")
            if resp.status_code == 200:
                commit_sha = resp.json().get("sha", source_url)
                return hashlib.sha256(commit_sha.encode()).hexdigest()
            return hashlib.sha256(source_url.encode()).hexdigest()


# ── API helpers ────────────────────────────────────────────────────────────────

def _build_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    else:
        logger.warning("GITHUB_TOKEN not set — limited to 60 requests/hour")
    return headers


def _parse_repo_url(url: str) -> tuple[str, str]:
    """
    Accepts:
      https://github.com/owner/repo
      https://github.com/owner/repo.git
      owner/repo
    """
    if url.startswith("http"):
        parts = urlparse(url).path.strip("/").rstrip(".git").split("/")
    else:
        parts = url.strip("/").split("/")
    if len(parts) < 2:
        raise ParseError(f"Cannot parse GitHub repo URL: {url!r}")
    return parts[0], parts[1]


async def _list_indexable_files(
    client: httpx.AsyncClient, owner: str, repo: str
) -> list[str]:
    """
    Fetch the full recursive file tree in one API call.
    Returns filtered list of file paths worth indexing.
    """
    try:
        resp = await client.get(f"/repos/{owner}/{repo}/git/trees/HEAD?recursive=1")
        resp.raise_for_status()
    except httpx.TimeoutException as exc:
        raise SourceUnreachableError(f"Timeout fetching tree for {owner}/{repo}") from exc
    except httpx.HTTPStatusError as exc:
        raise SourceUnreachableError(
            f"GitHub API returned {exc.response.status_code} for {owner}/{repo}"
        ) from exc
    except httpx.HTTPError as exc:
        raise SourceUnreachableError(f"Network error for {owner}/{repo}: {exc}") from exc
    tree = resp.json().get("tree", [])

    paths = []
    for item in tree:
        if item.get("type") != "blob":
            continue
        path: str = item["path"]
        size: int = item.get("size", 0)

        if size > _MAX_FILE_BYTES:
            continue
        if _should_skip(path):
            continue

        paths.append(path)

    return paths


def _should_skip(path: str) -> bool:
    parts = path.split("/")
    filename = parts[-1]

    # Skip if any directory component is in the skip list
    if any(part in _SKIP_DIRS for part in parts[:-1]):
        return True

    # Skip known lock/config filenames
    if filename in _SKIP_FILENAMES:
        return True

    # Skip by extension
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _INDEXABLE_EXTS:
        return True

    return False


async def _fetch_file(
    client: httpx.AsyncClient, owner: str, repo: str, path: str
) -> str | None:
    """
    Fetch a single file's content from GitHub API.
    Returns decoded UTF-8 string or None if fetch/decode fails.
    Respects rate limits via delay + X-RateLimit-Remaining header.
    """
    await asyncio.sleep(_REQUEST_DELAY)

    try:
        resp = await client.get(f"/repos/{owner}/{repo}/contents/{path}")
    except httpx.HTTPError as exc:
        logger.warning("failed to fetch %s: %s", path, exc)
        return None

    # Rate limit check — pause if running low
    remaining = int(resp.headers.get("X-RateLimit-Remaining", 999))
    if remaining < _RATE_LIMIT_BUFFER:
        reset_at = int(resp.headers.get("X-RateLimit-Reset", time.time() + 60))
        sleep_for = max(0, reset_at - time.time()) + 2
        logger.warning("rate limit low (%d remaining) — sleeping %.0fs", remaining, sleep_for)
        await asyncio.sleep(sleep_for)

    if resp.status_code == 404:
        logger.debug("file not found: %s", path)
        return None
    if resp.status_code != 200:
        logger.warning("unexpected status %d for %s", resp.status_code, path)
        return None

    data = resp.json()
    encoded = data.get("content", "")
    try:
        return base64.b64decode(encoded).decode("utf-8", errors="ignore")
    except Exception:
        return None
