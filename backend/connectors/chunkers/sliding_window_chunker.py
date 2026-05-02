from __future__ import annotations

from typing import Any

import tiktoken

from backend.models import Chunk, SourceType
from backend.strategies.base import ChunkerStrategy


class SlidingWindowChunker(ChunkerStrategy):
    """
    Token-based sliding window chunker.
    """

    def __init__(self, window_tokens: int = 512, overlap_tokens: int = 50) -> None:
        self._window = window_tokens
        self._overlap = overlap_tokens
        self._enc = tiktoken.encoding_for_model("gpt-4o")

    def chunk(self, content: str, metadata: dict[str, Any]) -> list[Chunk]:
        tokens = self._enc.encode(content)
        chunks: list[Chunk] = []
        step = self._window - self._overlap

        for i, start in enumerate(range(0, len(tokens), step)):
            window = tokens[start : start + self._window]
            if not window:
                break
            text = self._enc.decode(window)
            chunks.append(
                Chunk(
                    tenant_id=metadata.get("tenant_id", ""),
                    source_type=SourceType(metadata.get("source_type", "docs_site")),
                    source_url=metadata.get("source_url", ""),
                    content=text,
                    metadata={**metadata, "chunk_index": i},
                )
            )
        return chunks




