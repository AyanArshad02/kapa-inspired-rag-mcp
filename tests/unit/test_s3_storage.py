from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_storage():
    with patch("backend.strategies.storage.s3_storage.boto3") as mock_boto3:
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client
        from backend.strategies.storage.s3_storage import S3Storage
        storage = S3Storage()
        storage._s3 = mock_client
    return storage, mock_client


# ── is_s3_url ──────────────────────────────────────────────────────────────────

class TestIsS3Url:
    def test_s3_url_detected(self):
        from backend.strategies.storage.s3_storage import is_s3_url
        assert is_s3_url("s3://my-bucket/tenant/file.pdf") is True

    def test_https_url_not_s3(self):
        from backend.strategies.storage.s3_storage import is_s3_url
        assert is_s3_url("https://example.com/file.pdf") is False

    def test_local_path_not_s3(self):
        from backend.strategies.storage.s3_storage import is_s3_url
        assert is_s3_url("/tmp/upload.pdf") is False


# ── _parse_s3_url ──────────────────────────────────────────────────────────────

class TestParseS3Url:
    def test_parses_bucket_and_key(self):
        from backend.strategies.storage.s3_storage import _parse_s3_url
        bucket, key = _parse_s3_url("s3://my-bucket/tenant/report.pdf")
        assert bucket == "my-bucket"
        assert key == "tenant/report.pdf"

    def test_raises_on_missing_key(self):
        from backend.strategies.storage.s3_storage import _parse_s3_url
        with pytest.raises(ValueError):
            _parse_s3_url("s3://my-bucket")

    def test_nested_key(self):
        from backend.strategies.storage.s3_storage import _parse_s3_url
        bucket, key = _parse_s3_url("s3://bucket/a/b/c/file.md")
        assert bucket == "bucket"
        assert key == "a/b/c/file.md"


# ── S3Storage.upload ───────────────────────────────────────────────────────────

class TestS3StorageUpload:
    @pytest.mark.asyncio
    async def test_upload_returns_s3_url(self):
        storage, mock_client = _make_storage()
        mock_client.put_object.return_value = {}

        url = await storage.upload(b"hello pdf", "tenant1", "report.pdf")

        assert url.startswith("s3://")
        assert "tenant1/" in url
        assert url.endswith(".pdf")

    @pytest.mark.asyncio
    async def test_upload_calls_put_object(self):
        storage, mock_client = _make_storage()
        mock_client.put_object.return_value = {}

        await storage.upload(b"content", "t1", "doc.md")

        mock_client.put_object.assert_called_once()
        call_kwargs = mock_client.put_object.call_args[1]
        assert call_kwargs["ContentType"] == "text/markdown"
        assert call_kwargs["Body"] == b"content"

    @pytest.mark.asyncio
    async def test_upload_key_includes_uuid_suffix(self):
        storage, mock_client = _make_storage()
        mock_client.put_object.return_value = {}

        url1 = await storage.upload(b"data", "t1", "report.pdf")
        url2 = await storage.upload(b"data", "t1", "report.pdf")

        # Same tenant + filename should produce different keys (uuid suffix)
        assert url1 != url2


# ── S3Storage.download ─────────────────────────────────────────────────────────

class TestS3StorageDownload:
    @pytest.mark.asyncio
    async def test_download_returns_bytes(self):
        storage, mock_client = _make_storage()
        mock_body = MagicMock()
        mock_body.read.return_value = b"pdf content"
        mock_client.get_object.return_value = {"Body": mock_body}

        data = await storage.download("s3://my-bucket/t1/report.pdf")

        assert data == b"pdf content"
        mock_client.get_object.assert_called_once_with(Bucket="my-bucket", Key="t1/report.pdf")


# ── PDFConnector routing ───────────────────────────────────────────────────────

class TestPDFConnectorRouting:
    @pytest.mark.asyncio
    async def test_md_file_uses_heading_aware_chunker(self):
        from unittest.mock import AsyncMock, patch

        from backend.connectors.pdf_connector import PDFConnector
        from backend.connectors.chunkers.heading_aware_chunker import HeadingAwareChunker
        from backend.models import Chunk, SourceType

        fake_chunk = Chunk(content="section text", source_type=SourceType.PDF)
        mock_md_chunker = MagicMock(spec=HeadingAwareChunker)
        mock_md_chunker.chunk.return_value = [fake_chunk]

        connector = PDFConnector(md_chunker=mock_md_chunker)

        with patch.object(
            connector._storage, "download", new=AsyncMock(return_value=b"# Heading\n\nBody text")
        ):
            chunks = [c async for c in connector.fetch_chunks("s3://bucket/t1/doc.md", "t1")]

        mock_md_chunker.chunk.assert_called_once()
        assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_pdf_file_uses_recursive_chunker(self):
        from unittest.mock import AsyncMock, patch

        from backend.connectors.pdf_connector import PDFConnector
        from backend.connectors.chunkers.recursive_chunker import RecursiveChunker
        from backend.models import Chunk, SourceType

        fake_chunk = Chunk(content="pdf text", source_type=SourceType.PDF)
        mock_pdf_chunker = MagicMock(spec=RecursiveChunker)
        mock_pdf_chunker.chunk.return_value = [fake_chunk]

        connector = PDFConnector(pdf_chunker=mock_pdf_chunker)

        with patch.object(
            connector._storage, "download", new=AsyncMock(return_value=b"%PDF-1.4 fake")
        ), patch(
            "backend.connectors.pdf_connector._pdf_bytes_to_markdown",
            return_value="extracted markdown text",
        ):
            chunks = [c async for c in connector.fetch_chunks("s3://bucket/t1/report.pdf", "t1")]

        mock_pdf_chunker.chunk.assert_called_once()
        assert len(chunks) == 1
