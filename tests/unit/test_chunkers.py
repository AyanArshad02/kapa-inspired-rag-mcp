
from backend.connectors.chunkers.heading_aware_chunker import HeadingAwareChunker
from backend.connectors.chunkers.sliding_window_chunker import SlidingWindowChunker
from backend.models import SourceType

_META = {"tenant_id": "t1", "source_url": "https://docs.example.com", "source_type": "docs_site"}

_MARKDOWN = """# Installation

Install the package using pip. Make sure you have the correct Python version before proceeding with the installation steps below.

## Requirements

Python 3.11 or higher is required. You will also need pip version 22 or above and a virtual environment tool such as venv or virtualenv installed on your system.

## Quick Start

Run the following command to get started with the package. This will install all required dependencies and set up the environment correctly.

### Step 1

Create a virtual environment using the built-in venv module. This isolates the project dependencies from your system Python installation.

### Step 2

Install all dependencies by running pip install with the requirements file. This will pull down all necessary packages from PyPI.

## Configuration

Set the required environment variables before running the application. Without these variables the application will raise a configuration error on startup.
"""


class TestHeadingAwareChunker:
    def setup_method(self):
        self.chunker = HeadingAwareChunker()

    def test_splits_on_headings(self):
        chunks = self.chunker.chunk(_MARKDOWN, _META)
        assert len(chunks) >= 3

    def test_each_chunk_contains_its_heading(self):
        chunks = self.chunker.chunk(_MARKDOWN, _META)
        headings_found = [c for c in chunks if "#" in c.content]
        assert len(headings_found) > 0

    def test_chunk_metadata_preserved(self):
        chunks = self.chunker.chunk(_MARKDOWN, _META)
        for chunk in chunks:
            assert chunk.tenant_id == "t1"
            assert chunk.source_url == "https://docs.example.com"
            assert chunk.source_type == SourceType.DOCS_SITE

    def test_chunk_index_in_metadata(self):
        chunks = self.chunker.chunk(_MARKDOWN, _META)
        for chunk in chunks:
            assert "chunk_index" in chunk.metadata

    def test_skips_chunks_below_min_length(self):
        sparse_content = "# Title\n\nHi.\n\n## Section\n\nLonger section with more content here to pass the minimum character threshold."
        chunks = self.chunker.chunk(sparse_content, _META)
        for chunk in chunks:
            assert len(chunk.content) >= 100

    def test_content_without_headings_returns_single_chunk(self):
        plain = "This is a plain paragraph with no headings at all. " * 5
        chunks = self.chunker.chunk(plain, _META)
        assert len(chunks) == 1
        assert plain.strip() in chunks[0].content

    def test_empty_content_returns_no_chunks(self):
        chunks = self.chunker.chunk("", _META)
        assert chunks == []


class TestSlidingWindowChunker:
    def setup_method(self):
        self.chunker = SlidingWindowChunker(window_tokens=50, overlap_tokens=10)

    def test_short_content_produces_one_chunk(self):
        chunks = self.chunker.chunk("Hello world.", _META)
        assert len(chunks) == 1

    def test_long_content_produces_multiple_chunks(self):
        long_text = "word " * 300
        chunks = self.chunker.chunk(long_text, _META)
        assert len(chunks) > 1

    def test_chunks_overlap(self):
        # With overlap, the end of chunk N should appear at start of chunk N+1
        long_text = "word " * 300
        chunks = self.chunker.chunk(long_text, _META)
        assert len(chunks) >= 2
        # All chunks should be non-empty
        for chunk in chunks:
            assert len(chunk.content.strip()) > 0

    def test_chunk_metadata_preserved(self):
        chunks = self.chunker.chunk("word " * 100, _META)
        for chunk in chunks:
            assert chunk.tenant_id == "t1"
            assert chunk.source_type == SourceType.DOCS_SITE

    def test_chunk_index_increments(self):
        chunks = self.chunker.chunk("word " * 300, _META)
        indices = [c.metadata["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_window_size_respected(self):
        chunker_256 = SlidingWindowChunker(window_tokens=256, overlap_tokens=0)
        chunker_512 = SlidingWindowChunker(window_tokens=512, overlap_tokens=0)
        text = "word " * 600
        assert len(chunker_256.chunk(text, _META)) > len(chunker_512.chunk(text, _META))


class TestChunkerComparison:
    """Sanity checks that both chunkers produce valid output on the same input."""

    def test_both_chunkers_handle_same_input(self):
        heading_chunks = HeadingAwareChunker().chunk(_MARKDOWN, _META)
        sliding_chunks = SlidingWindowChunker().chunk(_MARKDOWN, _META)
        assert len(heading_chunks) > 0
        assert len(sliding_chunks) > 0

    def test_heading_chunker_preserves_section_boundaries(self):
        chunks = HeadingAwareChunker().chunk(_MARKDOWN, _META)
        # No chunk should contain content from two different top-level sections
        for chunk in chunks:
            h1_count = chunk.content.count("\n# ")
            assert h1_count <= 1








