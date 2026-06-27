"""
MCP server for kapa-inspired RAG.

Architecture: stateless — delegates to the query service HTTP API.
No asyncpg, no Redis, no Qdrant connections here.
The query service (localhost:8000) owns all that logic.

Tools:
  - search_knowledge_base      : calls POST /query on the query service
  - fetch_and_query_online_docs: fetches a URL on-the-fly, answers ephemerally

Token management:
  If LOAD_TEST_EMAIL + LOAD_TEST_PASSWORD are set, the TokenManager handles
  login + silent refresh automatically using the httpOnly refresh cookie.
  The access token is refreshed every 13 minutes — no restarts needed.
  Fallback: set KAPA_API_KEY directly to skip auto-login.
"""

from __future__ import annotations

import logging
import os
import sys
import time

import httpx
from mcp.server import FastMCP

from backend.mcp.tools import fetch_and_query_online_docs_impl, search_knowledge_base_http

# Redirect all logging to stderr so stdout stays clean for the stdio MCP protocol
logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

logger = logging.getLogger(__name__)

QUERY_SERVICE_URL = os.getenv("QUERY_SERVICE_URL", "http://54.156.190.134:9000")
_AUTH_URL = os.getenv("AUTH_URL", "http://54.156.190.134:8004")
_MCP_EMAIL = os.getenv("LOAD_TEST_EMAIL", "")
_MCP_PASSWORD = os.getenv("LOAD_TEST_PASSWORD", "")


class TokenManager:
    """
    Keeps a valid JWT access token by using the refresh token cookie.

    Flow:
      1. First get_token() call → login with email/password → stores refresh cookie in client
      2. Every subsequent call checks if token expires in <2 min
      3. If yes → POST /auth/refresh (client sends stored cookie) → new access token + new cookie
      4. If refresh fails → re-login with email/password
    """

    _ACCESS_TOKEN_TTL = 900  # 15 minutes in seconds
    _REFRESH_BEFORE = 120   # refresh 2 minutes before expiry

    def __init__(self, auth_url: str, email: str, password: str) -> None:
        self._auth_url = auth_url
        self._email = email
        self._password = password
        self._token = ""
        self._expires_at = 0.0
        # Single client instance — persists cookies between calls (refresh token lives here)
        self._client = httpx.AsyncClient(timeout=15)

    async def get_token(self) -> str:
        if time.monotonic() > self._expires_at - self._REFRESH_BEFORE:
            await self._refresh_or_login()
        return self._token

    async def _refresh_or_login(self) -> None:
        # Try silent refresh first (uses the httpOnly cookie stored in self._client)
        if self._token:
            try:
                resp = await self._client.post(f"{self._auth_url}/auth/refresh")
                if resp.status_code == 200:
                    self._token = resp.json()["access_token"]
                    self._expires_at = time.monotonic() + self._ACCESS_TOKEN_TTL
                    logger.warning("Token refreshed silently via refresh cookie")
                    return
            except Exception as exc:
                logger.warning("Refresh failed (%s) — falling back to re-login", exc)

        # Full re-login
        resp = await self._client.post(
            f"{self._auth_url}/auth/login",
            json={"email": self._email, "password": self._password},
        )
        resp.raise_for_status()
        self._token = resp.json()["access_token"]
        self._expires_at = time.monotonic() + self._ACCESS_TOKEN_TTL
        logger.warning("Logged in as %s", self._email)

    async def close(self) -> None:
        await self._client.aclose()


# Build token manager if credentials are available; fall back to static key otherwise
_token_manager: TokenManager | None = (
    TokenManager(_AUTH_URL, _MCP_EMAIL, _MCP_PASSWORD)
    if _MCP_EMAIL and _MCP_PASSWORD
    else None
)
_STATIC_API_KEY = os.getenv("KAPA_API_KEY", "")


mcp = FastMCP(
    name="kapa-rag",
    instructions=(
        "Use search_knowledge_base to answer questions from the tenant's ingested docs. "
        "Use fetch_and_query_online_docs when given a specific URL to consult — "
        "it fetches the page live and answers without persisting anything."
    ),
)


@mcp.tool()
async def search_knowledge_base(query: str) -> str:
    """
    Search the knowledge base and return a grounded answer with source URLs.

    Args:
        query: The question to answer.
    """
    if _token_manager:
        token = await _token_manager.get_token()
    else:
        token = _STATIC_API_KEY

    if not token:
        return (
            "No credentials configured. Set LOAD_TEST_EMAIL + LOAD_TEST_PASSWORD "
            "in .env, or set KAPA_API_KEY directly."
        )
    return await search_knowledge_base_http(QUERY_SERVICE_URL, query, token)


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



