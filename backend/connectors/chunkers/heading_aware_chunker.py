from __future__ import annotations

import re
from typing import Any

from backend.models import Chunk, SourceType
from backend.strategies.base import ChunkerStrategy

_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
_MIN_CHUNK_CHARS = 100


class HeadingAwareChunker(ChunkerStrategy):
    """
    Splits Markdown/HTML docs at H1/H2/H3 boundaries.

    Docs sites have deliberate heading structure. Splitting there keeps
    semantically related content together — a sliding window will cut
    across a heading boundary and mix unrelated sections.
    """

    def chunk(self, content: str, metadata: dict[str, Any]) -> list[Chunk]:
        sections = _split_on_headings(content)
        chunks: list[Chunk] = []

        for i, (heading, body) in enumerate(sections):
            text = f"{heading}\n\n{body}".strip() if heading else body.strip()
            if len(text) < _MIN_CHUNK_CHARS:
                continue
            chunks.append(
                Chunk(
                    tenant_id=metadata.get("tenant_id", ""),
                    source_type=SourceType(metadata.get("source_type", "docs_site")),
                    source_url=metadata.get("source_url", ""),
                    content=text,
                    metadata={**metadata, "chunk_index": i, "heading": heading},
                )
            )
        return chunks


def _split_on_headings(content: str) -> list[tuple[str, str]]:
    """Return (heading_line, body_text) pairs."""
    matches = list(_HEADING_RE.finditer(content))
    if not matches:
        return [("", content)]

    sections: list[tuple[str, str]] = []

    # text before the first heading
    if matches[0].start() > 0:
        sections.append(("", content[: matches[0].start()]))

    for i, match in enumerate(matches):
        heading = match.group(0)
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        sections.append((heading, content[body_start:body_end]))

    return sections



