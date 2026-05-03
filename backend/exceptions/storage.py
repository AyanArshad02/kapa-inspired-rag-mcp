from __future__ import annotations

from backend.exceptions.base import ErrorCode, KapaError


class StorageError(KapaError):
    """Any failure originating from the object storage layer (S3, etc.)."""
    component = "storage"


class S3UploadError(StorageError):
    """Failed to upload a file to S3.

    Retryable — transient S3 / network issue.
    """
    error_code = ErrorCode.S3_UPLOAD_FAILED
    retryable = True


class S3DownloadError(StorageError):
    """Failed to download a file from S3.

    Retryable — transient S3 / network issue.
    """
    error_code = ErrorCode.S3_DOWNLOAD_FAILED
    retryable = True


class S3DeleteError(StorageError):
    """Failed to delete a file from S3.

    Not retryable — if the object doesn't exist the operation is a no-op;
    if permissions are wrong, retrying won't help.
    """
    error_code = ErrorCode.S3_DELETE_FAILED
    retryable = False
