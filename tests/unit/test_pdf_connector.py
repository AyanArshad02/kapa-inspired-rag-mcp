from __future__ import annotations

import io
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.models import SourceType


def _make_fake_pdf_path(text: str = "Hello from page 1\n\nGoodbye from page 2") -> str:
    """Write a real single-page PDF to a temp file and return the path."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    doc.save(tmp.name)
    doc.close()
    tmp.close()
    return tmp.name


class TestPDFConnector:
    def test_source_type_is_pdf(self):
        from backend.connectors.pdf_connector import PDFConnector

        assert PDFConnector().source_type == SourceType.PDF

    async def test_fetch_chunks_yields_chunks(self):
        from backend.connectors.pdf_connector import PDFConnector

        path = _make_fake_pdf_path("FastAPI is a modern Python web framework.")
        connector = PDFConnector()
        chunks = [chunk async for chunk in connector.fetch_chunks(path, "tenant-1")]

        assert len(chunks) >= 1
        assert all(c.source_url == path for c in chunks)
        assert all(c.tenant_id == "tenant-1" for c in chunks)
        assert all(c.source_type == SourceType.PDF for c in chunks)

    async def test_compute_content_hash_is_deterministic(self):
        from backend.connectors.pdf_connector import PDFConnector

        path = _make_fake_pdf_path("Deterministic hashing test.")
        connector = PDFConnector()

        h1 = await connector.compute_content_hash(path)
        h2 = await connector.compute_content_hash(path)

        assert h1 == h2
        assert len(h1) == 64  # sha256 hex

    async def test_chunks_contain_extracted_text(self):
        from backend.connectors.pdf_connector import PDFConnector

        path = _make_fake_pdf_path("Dependency injection simplifies testing.")
        connector = PDFConnector()
        chunks = [chunk async for chunk in connector.fetch_chunks(path, "t1")]

        full_text = " ".join(c.content for c in chunks)
        assert "Dependency injection" in full_text
