from __future__ import annotations

from backend.exceptions.base import ErrorCode, KapaError


class IngestionError(KapaError):
    """Any failure during the data ingestion process."""
    component = "ingestion"


class SourceUnreachableError(IngestionError):
    """The source URL could not be fetched (HTTP error, DNS fail, timeout).

    Retryable — the source may be temporarily down.
    """
    error_code = ErrorCode.SOURCE_UNREACHABLE
    retryable = True


class ParseError(IngestionError):
    """The fetched content could not be parsed into chunks.

    Not retryable — if the content is malformed, re-fetching the same
    content will produce the same parse failure.
    """
    error_code = ErrorCode.PARSE_ERROR
    retryable = False
