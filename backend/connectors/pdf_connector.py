from __future__ import annotations

import hashlib
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

import pymupdf
import pymupdf4llm

from backend.connectors.base import ConnectorStrategy
from backend.connectors.chunkers.heading_aware_chunker import HeadingAwareChunker
from backend.connectors.chunkers.recursive_chunker import RecursiveChunker
from backend.exceptions import ParseError
from backend.models import Chunk, SourceType
from backend.strategies.base import ChunkerStrategy
from backend.strategies.storage.s3_storage import S3Storage, is_s3_url


class PDFConnector(ConnectorStrategy):
    """Handles tenant-uploaded files: PDF and Markdown.

    Source URL is always an  s3://  URL (set by the upload endpoint).
    Local file paths are still accepted for backward-compat in dev/tests.

    Routing by extension:
      .pdf  → pymupdf4llm (PDF → Markdown) → RecursiveChunker
      .md   → raw Markdown content          → HeadingAwareChunker
    """

    def __init__(
        self,
        pdf_chunker: ChunkerStrategy | None = None,
        md_chunker: ChunkerStrategy | None = None,
    ) -> None:
        self._pdf_chunker = pdf_chunker or RecursiveChunker()
        self._md_chunker = md_chunker or HeadingAwareChunker()
        self._storage = S3Storage()

    @property
    def source_type(self) -> SourceType:
        return SourceType.PDF

    async def fetch_chunks(
        self, source_url: str, tenant_id: str
    ) -> AsyncIterator[Chunk]:
        text, suffix = await self._get_text_and_suffix(source_url)
        chunker = self._md_chunker if suffix == ".md" else self._pdf_chunker
        metadata = {
            "tenant_id": tenant_id,
            "source_url": source_url,
            "source_type": SourceType.PDF.value,
        }
        for chunk in chunker.chunk(text, metadata):
            yield chunk

    async def compute_content_hash(self, source_url: str) -> str:
        if is_s3_url(source_url):
            data = await self._storage.download(source_url)
        else:
            data = Path(source_url).read_bytes()
        return hashlib.sha256(data).hexdigest()

    # ── Private ───────────────────────────────────────────────────────────────

    async def _get_text_and_suffix(self, source_url: str) -> tuple[str, str]:
        suffix = Path(source_url).suffix.lower()

        if is_s3_url(source_url):
            raw = await self._storage.download(source_url)
            if suffix == ".md":
                return raw.decode("utf-8", errors="replace"), ".md"
            return _pdf_bytes_to_markdown(raw), ".pdf"

        # Local file path (dev / tests)
        if suffix == ".md":
            return Path(source_url).read_text(encoding="utf-8"), ".md"
        return _extract_text_from_path(source_url), ".pdf"


# ── PDF extraction helpers ─────────────────────────────────────────────────────

def _extract_text_from_path(path: str) -> str:
    try:
        doc = pymupdf.open(path)
        pages = list(range(len(doc)))
        doc.close()
        md = pymupdf4llm.to_markdown(path, pages=pages, show_progress=False)
        return md.replace("\n-----\n", "\n\n")
    except Exception as exc:
        raise ParseError(f"Failed to extract text from PDF {path}: {exc}") from exc


def _pdf_bytes_to_markdown(data: bytes) -> str:
    """Write bytes to a NamedTemporaryFile, extract with pymupdf4llm, clean up."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name
    try:
        return _extract_text_from_path(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
