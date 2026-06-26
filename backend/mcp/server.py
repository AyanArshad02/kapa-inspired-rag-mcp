"""
MCP server for kapa-inspired RAG.

Architecture: stateless — delegates to the query service HTTP API.
No asyncpg, no Redis, no Qdrant connections here.
The query service (localhost:8000) owns all that logic.

Tools:
  - search_knowledge_base      : calls POST /query on the query service
  - fetch_and_query_online_docs: fetches a URL on-the-fly, answers ephemerally
"""

from __future__ import annotations

import logging
import os
import sys

from mcp.server import FastMCP

from backend.mcp.tools import fetch_and_query_online_docs_impl, search_knowledge_base_http

# Redirect all logging to stderr so stdout stays clean for the stdio MCP protocol
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

logger = logging.getLogger(__name__)

QUERY_SERVICE_URL = os.getenv("QUERY_SERVICE_URL", "http://localhost:8000")

mcp = FastMCP(
    name="kapa-rag",
    instructions=(
        "Use search_knowledge_base to answer questions from the tenant's ingested docs. "
        "Use fetch_and_query_online_docs when given a specific URL to consult — "
        "it fetches the page live and answers without persisting anything."
    ),
)


_DEFAULT_API_KEY = os.getenv("KAPA_API_KEY", "")
_DEFAULT_TENANT_ID = os.getenv("KAPA_TENANT_ID", "")


@mcp.tool()
async def search_knowledge_base(
    query: str,
    api_key: str = _DEFAULT_API_KEY,
    tenant_id: str = _DEFAULT_TENANT_ID,
) -> str:
    """
    Search the knowledge base and return a grounded answer with source URLs.

    Args:
        query:     The question to answer.
        api_key:   JWT access token (defaults to KAPA_API_KEY env var).
        tenant_id: Tenant ID (defaults to KAPA_TENANT_ID env var).
    """
    resolved_key = api_key or _DEFAULT_API_KEY
    if not resolved_key:
        return "No API key provided. Set KAPA_API_KEY env var or pass api_key explicitly."
    return await search_knowledge_base_http(QUERY_SERVICE_URL, query, resolved_key)


@mcp.tool()
async def fetch_and_query_online_docs(url: str, query: str) -> str:
    """
    Fetch a documentation URL on-the-fly, extract relevant sections, and answer the query.
    Nothing is persisted — this is a one-shot ephemeral lookup.

    Args:
        url:   The documentation URL to fetch (must be http/https).
        query: The question to answer from the fetched content.
    """
    if not url.startswith(("http://", "https://")):
        return "URL must start with http:// or https://"
    return await fetch_and_query_online_docs_impl(url, query)


if __name__ == "__main__":
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    mcp.run(transport=transport)
