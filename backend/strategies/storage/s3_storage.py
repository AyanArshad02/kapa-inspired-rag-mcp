from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from backend.config import settings
from backend.exceptions import S3DeleteError, S3DownloadError, S3UploadError

logger = logging.getLogger(__name__)

# S3 URL prefix we write and recognise internally
_S3_SCHEME = "s3://"


class S3Storage:
    """Thin wrapper around boto3 for uploading and downloading tenant files.

    All I/O is delegated to a thread pool via asyncio.to_thread so callers
    can await it without blocking the event loop.

    URL format stored in the database:  s3://<bucket>/<key>
    (e.g.  s3://kapa-rag-uploads/tenant_abc/report_<uuid>.pdf)
    """

    def __init__(self) -> None:
        kwargs: dict = {"region_name": settings.s3_region}
        if settings.aws_access_key_id:
            kwargs["aws_access_key_id"] = settings.aws_access_key_id
            kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        self._s3 = boto3.client("s3", **kwargs)
        self._bucket = settings.s3_bucket

    # ── Public API ─────────────────────────────────────────────────────────────

    async def upload(
        self, file_bytes: bytes, tenant_id: str, filename: str
    ) -> str:
        """Upload raw bytes and return the internal s3:// URL.

        The key is  <tenant_id>/<stem>_<uuid><suffix>  so uploads from
        different tenants never collide even with identical filenames.
        """
        suffix = Path(filename).suffix.lower()
        stem = Path(filename).stem
        key = f"{tenant_id}/{stem}_{uuid.uuid4().hex}{suffix}"

        await asyncio.to_thread(self._upload_sync, file_bytes, key, suffix)
        s3_url = f"{_S3_SCHEME}{self._bucket}/{key}"
        logger.info("s3: uploaded %s → %s", filename, s3_url)
        return s3_url

    def presign_upload(
        self, tenant_id: str, filename: str, expires_in: int = 300
    ) -> tuple[str, str]:
        """Generate a presigned PUT URL for direct browser-to-S3 upload.

        Returns (presigned_url, s3_url).  The caller should:
          1. PUT the file bytes directly to presigned_url from the browser.
          2. POST the returned s3_url to /ingest/confirm to start processing.
        """
        suffix = Path(filename).suffix.lower()
        stem = Path(filename).stem
        key = f"{tenant_id}/{stem}_{uuid.uuid4().hex}{suffix}"
        content_type = _content_type(suffix)

        presigned_url = self._s3.generate_presigned_url(
            "put_object",
            Params={"Bucket": self._bucket, "Key": key, "ContentType": content_type},
            ExpiresIn=expires_in,
        )
        s3_url = f"{_S3_SCHEME}{self._bucket}/{key}"
        logger.info("s3: presigned PUT for %s → %s", filename, s3_url)
        return presigned_url, s3_url

    async def download(self, s3_url: str) -> bytes:
        """Download and return raw bytes for an s3:// URL."""
        bucket, key = _parse_s3_url(s3_url)
        data = await asyncio.to_thread(self._download_sync, bucket, key)
        logger.info("s3: downloaded %s (%d bytes)", s3_url, len(data))
        return data

    async def delete(self, s3_url: str) -> None:
        """Delete an object. Silently ignores 404 (already deleted)."""
        bucket, key = _parse_s3_url(s3_url)
        await asyncio.to_thread(self._delete_sync, bucket, key)
        logger.info("s3: deleted %s", s3_url)

    # ── Sync helpers (run inside thread pool) ─────────────────────────────────

    def _upload_sync(self, data: bytes, key: str, suffix: str) -> None:
        content_type = _content_type(suffix)
        try:
            self._s3.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
            )
        except (ClientError, BotoCoreError) as exc:
            raise S3UploadError(str(exc)) from exc

    def _download_sync(self, bucket: str, key: str) -> bytes:
        try:
            resp = self._s3.get_object(Bucket=bucket, Key=key)
            return resp["Body"].read()
        except (ClientError, BotoCoreError) as exc:
            raise S3DownloadError(str(exc)) from exc

    def _delete_sync(self, bucket: str, key: str) -> None:
        try:
            self._s3.delete_object(Bucket=bucket, Key=key)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "NoSuchKey":
                return
            raise S3DeleteError(str(exc)) from exc
        except BotoCoreError as exc:
            raise S3DeleteError(str(exc)) from exc


# ── Helpers ───────────────────────────────────────────────────────────────────

def is_s3_url(url: str) -> bool:
    return url.startswith(_S3_SCHEME)


def _parse_s3_url(s3_url: str) -> tuple[str, str]:
    """'s3://bucket/path/to/key' → ('bucket', 'path/to/key')"""
    without_scheme = s3_url[len(_S3_SCHEME):]
    bucket, _, key = without_scheme.partition("/")
    if not bucket or not key:
        raise ValueError(f"Invalid S3 URL: {s3_url!r}")
    return bucket, key


def _content_type(suffix: str) -> str:
    return {
        ".pdf": "application/pdf",
        ".md": "text/markdown",
    }.get(suffix, "application/octet-stream")
