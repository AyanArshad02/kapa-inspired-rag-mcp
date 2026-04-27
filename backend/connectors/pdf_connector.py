from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from pathlib import Path

import pymupdf
import pymupdf4llm

from backend.connectors.base import ConnectorStrategy
from backend.connectors.chunkers.recursive_chunker import RecursiveChunker
from backend.models import Chunk, SourceType
from backend.strategies.base import ChunkerStrategy

class PDFConnector(ConnectorStrategy):
    """
    Extracts text from a PDF using pymupdf4llm (PDF → Markdown) and splits
    with RecursiveChunker:
      - pymupdf4llm handles font-encoded PDFs, falls back to Tesseract on scanned pages
      - RecursiveChunker splits at natural Markdown paragraph boundaries
    """

    def __init__(self, chunker: ChunkerStrategy | None = None) -> None:
        self._chunker = chunker or RecursiveChunker()

    @property
    def source_type(self) -> SourceType:
        return SourceType.PDF

    async def fetch_chunks(
        self, source_url: str, tenant_id: str
    ) -> AsyncIterator[Chunk]:
        text = _extract_text(source_url)
        metadata = {
            "tenant_id": tenant_id,
            "source_url": source_url,
            "source_type": SourceType.PDF.value,
        }
        for chunk in self._chunker.chunk(text, metadata):
            yield chunk

    async def compute_content_hash(self, source_url: str) -> str:
        data = Path(source_url).read_bytes()
        return hashlib.sha256(data).hexdigest()


def _extract_text(path: str) -> str:
    """Extract Markdown from all pages of a PDF via pymupdf4llm."""
    doc = pymupdf.open(path)
    pages = list(range(len(doc)))
    doc.close()
    md = pymupdf4llm.to_markdown(path, pages=pages, show_progress=False)
    return md.replace("\n-----\n", "\n\n")



