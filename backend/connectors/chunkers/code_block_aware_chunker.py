from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import tiktoken

from backend.connectors.chunkers.heading_aware_chunker import HeadingAwareChunker
from backend.connectors.chunkers.recursive_chunker import RecursiveChunker
from backend.models import Chunk, SourceType
from backend.strategies.base import ChunkerStrategy

# ── Language regex patterns ────────────────────────────────────────────────────

# JS/TS: named functions, arrow functions assigned to const, class declarations
_JS_TS_PATTERN = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function\s+\w|class\s+\w|const\s+\w+\s*=\s*(?:async\s+)?\()"
)

# Go: top-level func declarations (including methods with receivers)
_GO_PATTERN = re.compile(r"^func\s+")

# Java / Kotlin: method declarations (any visibility modifier)
_JAVA_PATTERN = re.compile(
    r"^\s*(?:public|private|protected|static|final|abstract|override)"
    r"[\s\w<>\[\]]*\s+\w+\s*\("
)

# Rust: fn declarations (pub optional, async optional)
_RUST_PATTERN = re.compile(r"^(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+\w")

_JS_TS_EXTS  = {".ts", ".js", ".tsx", ".jsx", ".mjs", ".cjs"}
_MARKUP_EXTS = {".md", ".mdx", ".rst"}


class CodeBlockAwareChunker(ChunkerStrategy):
    """
    Splits source code at function/class boundaries instead of token count.

    For Python uses the ast module — exact boundaries, zero false splits.
    For other languages uses regex on function/class declaration lines.
    Markdown and RST files are delegated to HeadingAwareChunker.
    Everything else falls back to RecursiveChunker.
    """

    def __init__(self, max_tokens: int = 512) -> None:
        self._max = max_tokens
        self._enc = tiktoken.encoding_for_model("gpt-4o")
        self._heading_chunker = HeadingAwareChunker()
        self._recursive_chunker = RecursiveChunker(max_tokens=max_tokens)

    def chunk(self, content: str, metadata: dict[str, Any]) -> list[Chunk]:
        ext = Path(metadata.get("source_url", "")).suffix.lower()

        if ext == ".py":
            return self._chunk_python(content, metadata)
        elif ext in _JS_TS_EXTS:
            return self._chunk_by_regex(content, metadata, _JS_TS_PATTERN)
        elif ext == ".go":
            return self._chunk_by_regex(content, metadata, _GO_PATTERN)
        elif ext in {".java", ".kt"}:
            return self._chunk_by_regex(content, metadata, _JAVA_PATTERN)
        elif ext == ".rs":
            return self._chunk_by_regex(content, metadata, _RUST_PATTERN)
        elif ext in _MARKUP_EXTS:
            return self._heading_chunker.chunk(content, metadata)
        else:
            return self._recursive_chunker.chunk(content, metadata)

    # ── Python ─────────────────────────────────────────────────────────────────

    def _chunk_python(self, content: str, metadata: dict[str, Any]) -> list[Chunk]:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return self._recursive_chunker.chunk(content, metadata)

        lines = content.splitlines()
        chunks: list[Chunk] = []

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                block = _extract_lines(lines, node)
                chunks.append(_make_chunk(block, metadata, {
                    "block_type": "function",
                    "block_name": node.name,
                }))

            elif isinstance(node, ast.ClassDef):
                class_src = _extract_lines(lines, node)

                if self._token_count(class_src) <= self._max:
                    # Small class — keep whole class as one chunk
                    chunks.append(_make_chunk(class_src, metadata, {
                        "block_type": "class",
                        "block_name": node.name,
                    }))
                else:
                    # Large class — header chunk + one chunk per method
                    header = _build_class_header(node, lines)
                    if header:
                        chunks.append(_make_chunk(header, metadata, {
                            "block_type": "class_header",
                            "block_name": node.name,
                        }))
                    for child in node.body:
                        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            method_src = _extract_lines(lines, child)
                            chunks.append(_make_chunk(method_src, metadata, {
                                "block_type": "method",
                                "block_name": f"{node.name}.{child.name}",
                            }))

        # If file has no top-level functions/classes (e.g. pure config file)
        if not chunks:
            return self._recursive_chunker.chunk(content, metadata)

        return chunks

    # ── Regex fallback ──────────────────────────────────────────────────────────

    def _chunk_by_regex(
        self,
        content: str,
        metadata: dict[str, Any],
        pattern: re.Pattern,  # type: ignore[type-arg]
    ) -> list[Chunk]:
        """
        Split at lines matching the declaration pattern.
        Each declaration line starts a new block — everything until the
        next declaration belongs to the previous block.
        """
        lines = content.splitlines(keepends=True)
        boundaries = [i for i, line in enumerate(lines) if pattern.match(line)]

        if not boundaries:
            return self._recursive_chunker.chunk(content, metadata)

        # Include any leading content (imports, module docstring) as first block
        if boundaries[0] > 0:
            boundaries = [0] + boundaries

        chunks: list[Chunk] = []
        for i, start in enumerate(boundaries):
            end = boundaries[i + 1] if i + 1 < len(boundaries) else len(lines)
            block = "".join(lines[start:end]).strip()
            if not block:
                continue
            # Block too large (e.g. a huge generated file) — split recursively
            if self._token_count(block) > self._max * 2:
                chunks.extend(self._recursive_chunker.chunk(block, metadata))
            else:
                chunks.append(_make_chunk(block, metadata, {"block_type": "code_block"}))

        return chunks

    def _token_count(self, text: str) -> int:
        return len(self._enc.encode(text))


# ── AST helpers ────────────────────────────────────────────────────────────────

def _extract_lines(lines: list[str], node: ast.AST) -> str:
    """Extract the exact source lines covered by an AST node."""
    start: int = getattr(node, "lineno", 1) - 1
    end: int = getattr(node, "end_lineno", start + 1)
    return "\n".join(lines[start:end])


def _build_class_header(node: ast.ClassDef, lines: list[str]) -> str:
    """
    Build a summary chunk for a large class:
      - class declaration line (includes base classes)
      - class docstring if present
      - one signature line per method (so the LLM knows what methods exist)
    """
    first_line = lines[node.lineno - 1]  # e.g. "class QueryPipeline(BaseClass):"
    parts = [first_line]

    docstring = ast.get_docstring(node)
    if docstring:
        short_doc = docstring.split("\n")[0][:120]
        parts.append(f'    """{short_doc}"""')

    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig = lines[child.lineno - 1].rstrip()
            parts.append(f"    {sig.lstrip()}  # ...")

    return "\n".join(parts)


def _make_chunk(content: str, metadata: dict[str, Any], extra: dict[str, Any]) -> Chunk:
    return Chunk(
        tenant_id=metadata.get("tenant_id", ""),
        source_url=metadata.get("source_url", ""),
        source_type=SourceType(metadata.get("source_type", "github")),
        content=content.strip(),
        metadata={**metadata, **extra},
    )



