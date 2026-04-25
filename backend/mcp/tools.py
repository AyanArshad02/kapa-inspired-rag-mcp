from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

import httpx
import numpy as np
from bs4 import BeautifulSoup

from backend.connectors.chunkers.heading_aware_chunker import HeadingAwareChunker
from backend.core.context_window_builder import ContextWindowBuilder
from backend.core.query_pipeline import QueryPipeline
from backend.models import SourceType
from backend.strategies.embedding.openai_embedding import OpenAIEmbedding
from backend.strategies.llm.openai_llm import OpenAILLM

logger = logging.getLogger(__name__)

_EPHEMERAL_TOP_K = 5


async def search_knowledge_base_http(
    query_service_url: str,
    query: str,
    api_key: str,
) -> str:
    """Call the query service HTTP API — no direct infra connections needed."""
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(
                f"{query_service_url}/query",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"query": query, "stream": False},
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return f"Query service error: {exc}"

    data = resp.json()
    source_urls = data.get("source_urls", [])
    cached = data.get("cached", False)

    lines = [data["answer"], "", "**Sources:**"]
    lines.extend(f"- {url}" for url in source_urls)
    if cached:
        lines.append("\n_Served from cache._")
    return "\n".join(lines)


async def search_knowledge_base_impl(
    pipeline: QueryPipeline,
    query: str,
    tenant_id: str,
) -> str:
    """Run the full RAG pipeline directly (used in tests)."""
    result = await pipeline.handle(query, tenant_id, uuid4())
    source_urls = list({c.source_url for c in result.source_chunks})

    lines = [result.answer, "", "**Sources:**"]
    lines.extend(f"- {url}" for url in source_urls)
    if result.cached:
        lines.append("\n_Served from cache._")
    return "\n".join(lines)


async def fetch_and_query_online_docs_impl(url: str, query: str) -> str:
    """Fetch a URL on-the-fly, chunk it, and answer ephemerally — nothing persisted."""
    # 1. Fetch the page
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        try:
            resp = await client.get(url, headers={"User-Agent": "kapa-rag-mcp/1.0"})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            return f"Failed to fetch URL: {exc}"

    # 2. Extract readable text
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)

    if not text.strip():
        return "Could not extract readable text from the provided URL."

    # 3. Chunk with HeadingAwareChunker
    chunker = HeadingAwareChunker()
    metadata = {"tenant_id": "ephemeral", "source_type": "docs_site", "source_url": url}
    chunks = chunker.chunk(content=text, metadata=metadata)

    if not chunks:
        return "No content sections could be extracted from the URL."

    # 4. Embed query + all chunks in parallel
    embedder = OpenAIEmbedding()
    chunk_texts = [c.content for c in chunks]
    query_vecs, chunk_vecs = await asyncio.gather(
        embedder.embed([query]),
        embedder.embed(chunk_texts),
    )

    # 5. Cosine similarity — pick top-k
    q_vec = np.array(query_vecs[0])
    c_matrix = np.array(chunk_vecs)
    q_norm = q_vec / (np.linalg.norm(q_vec) + 1e-9)
    c_norms = c_matrix / (np.linalg.norm(c_matrix, axis=1, keepdims=True) + 1e-9)
    scores = (c_norms @ q_norm).tolist()
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:_EPHEMERAL_TOP_K]
    top_chunks = [chunks[i] for i in top_indices]

    # 6. Build context window + generate answer
    builder = ContextWindowBuilder()
    context = builder.build(query=query, chunks=top_chunks, history=[], tenant_id="ephemeral")
    llm = OpenAILLM()
    result = await llm.generate(context)

    return result.answer
