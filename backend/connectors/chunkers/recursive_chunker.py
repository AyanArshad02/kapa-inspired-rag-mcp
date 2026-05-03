from __future__ import annotations

from typing import Any

import tiktoken

from backend.models import Chunk, SourceType
from backend.strategies.base import ChunkerStrategy


class RecursiveChunker(ChunkerStrategy):
    """
    Hierarchical text splitter: tries separators in order (\n\n → \n → . → space)
    until each piece fits within max_tokens. Adds overlap from the previous chunk.

    Performs best on Markdown output from pymupdf4llm because paragraph breaks
    (\n\n) align with semantic boundaries already present in the text.
    """

    _SEPS = ["\n\n", "\n", ". ", " "]

    def __init__(self, max_tokens: int = 512, overlap_tokens: int = 50) -> None:
        self._max = max_tokens
        self._overlap = overlap_tokens
        self._enc = tiktoken.encoding_for_model("gpt-4o")

    def chunk(self, content: str, metadata: dict[str, Any]) -> list[Chunk]:
        raw = self._split(content, 0)
        out: list[Chunk] = []
        for i, text in enumerate(raw):
            if not text.strip():
                continue
            if i > 0 and self._overlap > 0:
                prev_tokens = self._enc.encode(raw[i - 1])
                text = self._enc.decode(prev_tokens[-self._overlap :]) + " " + text
            out.append(
                Chunk(
                    tenant_id=metadata.get("tenant_id", ""),
                    source_type=SourceType(metadata.get("source_type", "pdf")),
                    source_url=metadata.get("source_url", ""),
                    content=text.strip(),
                    metadata={**metadata, "chunk_index": i, "chunk_type": "recursive"},
                )
            )
        return out

    def _token_count(self, text: str) -> int:
        return len(self._enc.encode(text))

    def _split(self, text: str, sep_index: int) -> list[str]:
        if self._token_count(text) <= self._max:
            return [text]
        if sep_index >= len(self._SEPS):
            return self._sliding_split(text)

        sep = self._SEPS[sep_index]
        parts = text.split(sep)
        result: list[str] = []
        current = ""

        for part in parts:
            if not part.strip():
                continue
            candidate = (current + sep + part) if current else part
            if self._token_count(candidate) <= self._max:
                current = candidate
            else:
                if current:
                    result.append(current.strip())
                if self._token_count(part) > self._max:
                    result.extend(self._split(part, sep_index + 1))
                    current = ""
                else:
                    current = part

        if current.strip():
            result.append(current.strip())
        return result

    def _sliding_split(self, text: str) -> list[str]:
        tokens = self._enc.encode(text)
        step = self._max - self._overlap
        return [
            self._enc.decode(tokens[s : s + self._max])
            for s in range(0, len(tokens), step)
            if tokens[s : s + self._max]
        ]
