from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator

import httpx
from bs4 import BeautifulSoup

from backend.connectors.base import ConnectorStrategy
from backend.connectors.chunkers.heading_aware_chunker import HeadingAwareChunker
from backend.models import Chunk, SourceType
from backend.strategies.base import ChunkerStrategy


class DocsConnector(ConnectorStrategy):
    """Fetches HTML documentation pages and yields chunks.

    Uses HeadingAwareChunker by default — locked in after Phase 1
    empirical comparison shows it outperforms sliding window on docs.
    Chunker is injected so experiments can swap it without subclassing.
    """

    def __init__(self, chunker: ChunkerStrategy | None = None) -> None:
        self._chunker = chunker or HeadingAwareChunker()

    @property
    def source_type(self) -> SourceType:
        return SourceType.DOCS_SITE

    async def fetch_chunks(
        self, source_url: str, tenant_id: str
    ) -> AsyncIterator[Chunk]:
        html = await _fetch_html(source_url)
        markdown = _html_to_markdown(html)
        metadata = {
            "tenant_id": tenant_id,
            "source_url": source_url,
            "source_type": SourceType.DOCS_SITE.value,
        }
        for chunk in self._chunker.chunk(markdown, metadata):
            yield chunk

    async def compute_content_hash(self, source_url: str) -> str:
        html = await _fetch_html(source_url)
        return hashlib.sha256(html.encode()).hexdigest()


async def _fetch_html(url: str) -> str:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": "kapa-rag-bot/1.0"})
        response.raise_for_status()
        return response.text


def _html_to_markdown(html: str) -> str:
    """Extract readable text from HTML, preserving heading structure."""
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()

    lines: list[str] = []
    for tag in soup.find_all(["h1", "h2", "h3", "p", "li", "pre", "code"]):
        text = tag.get_text(separator=" ", strip=True)
        if not text:
            continue
        if tag.name == "h1":
            lines.append(f"# {text}")
        elif tag.name == "h2":
            lines.append(f"## {text}")
        elif tag.name == "h3":
            lines.append(f"### {text}")
        else:
            lines.append(text)

    return "\n\n".join(lines)
