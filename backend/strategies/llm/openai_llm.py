from __future__ import annotations

from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker
from backend.models import ContextWindow, QueryResult
from backend.strategies.base import LLMStrategy

_SYSTEM_PROMPT = """\
You are a precise technical assistant. Answer the user's question using ONLY the context passages provided.

Rules:
- If the answer is in the context, give a clear and direct answer.
- If the answer is not in the context, respond: "I don't have enough information to answer that based on the available documentation."
- Never fabricate information.
- When the answer comes from a specific source, mention it naturally (e.g. "According to the FastAPI docs...").
- Keep answers concise. Do not pad with filler sentences.\
"""


def _build_messages(context: ContextWindow) -> list[dict]:
    context_text = "\n\n---\n\n".join(
        f"[Source: {c.source_url}]\n{c.content}" for c in context.chunks
    )
    messages: list[dict] = [{"role": "system", "content": _SYSTEM_PROMPT}]

    for turn in context.conversation_history:
        messages.append({"role": "user", "content": turn.user_message})
        messages.append({"role": "assistant", "content": turn.assistant_message})

    messages.append({
        "role": "user",
        "content": f"Context:\n{context_text}\n\nQuestion: {context.query}",
    })
    return messages


def _select_model(context: ContextWindow) -> str:
    """Route to fast model for small contexts, default model for large ones."""
    if context.total_tokens <= settings.llm_fast_token_threshold:
        return settings.llm_fast_model
    return settings.llm_default_model


class OpenAILLM(LLMStrategy):
    """GPT-4o / GPT-4o-mini with automatic model routing and circuit breaker."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._circuit = CircuitBreaker(
            "openai-llm", failure_threshold=3, recovery_timeout=30.0
        )

    async def generate(self, context: ContextWindow) -> QueryResult:
        messages = _build_messages(context)
        model = _select_model(context)

        response = await self._circuit.call(
            self._client.chat.completions.create,
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=1024,
        )
        return QueryResult(
            answer=response.choices[0].message.content or "",
            source_chunks=context.chunks,
        )

    async def generate_stream(self, context: ContextWindow) -> AsyncIterator[str]:
        messages = _build_messages(context)
        model = _select_model(context)

        # Circuit breaker covers the initial connection; iteration happens outside it
        stream = await self._circuit.call(
            self._client.chat.completions.create,
            model=model,
            messages=messages,
            temperature=0.1,
            max_tokens=1024,
            stream=True,
        )

        async for chunk in stream:
            token = chunk.choices[0].delta.content
            if token:
                yield token
