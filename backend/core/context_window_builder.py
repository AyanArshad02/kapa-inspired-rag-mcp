from __future__ import annotations

import tiktoken

from backend.config import settings
from backend.models import Chunk, ContextWindow, Turn

_ENCODING = tiktoken.encoding_for_model("gpt-4o")

# Token budget allocation out of max_context_tokens (6000)
_SYSTEM_RESERVED = 150   # system prompt
_QUERY_RESERVED = 200    # user query
_HISTORY_RESERVED = 600  # conversation history (3 turns × ~200 tokens)
_OVERHEAD = _SYSTEM_RESERVED + _QUERY_RESERVED + _HISTORY_RESERVED


def _count(text: str) -> int:
    return len(_ENCODING.encode(text))


class ContextWindowBuilder:
    """
    Fits retrieved chunks into the token budget before handing off to the LLM.

    Budget: 6000 total
      - 150  system prompt
      - 200  query
      - 600  conversation history
      - 5050 chunks, greedy fill, drop trailing chunks if they don't fit

    Why greedy and not truncate-last?
    Reranker already ordered chunks by relevance descending, so dropping
    the last chunk(s) always discards the least relevant ones.
    """

    def __init__(self, max_tokens: int = settings.max_context_tokens) -> None:
        self._chunk_budget = max_tokens - _OVERHEAD

    def build(
        self,
        query: str,
        chunks: list[Chunk],
        history: list[Turn],
        tenant_id: str,
    ) -> ContextWindow:
        selected: list[Chunk] = []
        used = 0

        for chunk in chunks:
            n = _count(chunk.content)
            if used + n > self._chunk_budget:
                break
            selected.append(chunk)
            used += n

        total_tokens = (
            used
            + _count(query)
            + sum(_count(t.user_message + t.assistant_message) for t in history)
            + _SYSTEM_RESERVED
        )

        return ContextWindow(
            query=query,
            chunks=selected,
            conversation_history=history,
            total_tokens=total_tokens,
            tenant_id=tenant_id,
        )




