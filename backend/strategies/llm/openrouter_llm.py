from __future__ import annotations

from collections.abc import AsyncIterator

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.exceptions import LLMInvalidResponseError, LLMRateLimitError, LLMTimeoutError
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


class OpenRouterLLM(LLMStrategy):
    """OpenRouter-hosted LLM via OpenAI-compatible API, with circuit breaker.

    Uses a single model — no routing logic needed (unlike OpenAILLM which routes
    between GPT-4o and GPT-4o-mini based on token count).
    """

    def __init__(self) -> None:
        self._model = settings.openrouter_model
        self._client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
            default_headers={
                "HTTP-Referer": "https://github.com/AyanArshad02/kapa-inspired-rag-mcp",
                "X-Title": "kapa-inspired RAG MCP",
            },
        )
        self._circuit = CircuitBreaker(
            "openrouter-llm", failure_threshold=3, recovery_timeout=30.0
        )

    async def generate(self, context: ContextWindow) -> QueryResult:
        messages = _build_messages(context)

        try:
            response = await self._circuit.call(
                self._client.chat.completions.create,
                model=self._model,
                messages=messages,
                temperature=0.1,
                max_tokens=1024,
            )
        except CircuitOpenError as exc:
            raise LLMTimeoutError("LLM circuit open — too many recent failures") from exc
        except RateLimitError as exc:
            raise LLMRateLimitError(str(exc)) from exc
        except APITimeoutError as exc:
            raise LLMTimeoutError(str(exc)) from exc
        except APIError as exc:
            raise LLMInvalidResponseError(str(exc)) from exc

        return QueryResult(
            answer=response.choices[0].message.content or "",
            source_chunks=context.chunks,
        )

    async def generate_stream(self, context: ContextWindow) -> AsyncIterator[str]:
        messages = _build_messages(context)

        try:
            stream = await self._circuit.call(
                self._client.chat.completions.create,
                model=self._model,
                messages=messages,
                temperature=0.1,
                max_tokens=1024,
                stream=True,
            )
        except CircuitOpenError as exc:
            raise LLMTimeoutError("LLM circuit open — too many recent failures") from exc
        except RateLimitError as exc:
            raise LLMRateLimitError(str(exc)) from exc
        except APITimeoutError as exc:
            raise LLMTimeoutError(str(exc)) from exc
        except APIError as exc:
            raise LLMInvalidResponseError(str(exc)) from exc

        try:
            async for chunk in stream:
                token = chunk.choices[0].delta.content
                if token:
                    yield token
        except APIError as exc:
            raise LLMInvalidResponseError(f"Stream interrupted: {exc}") from exc





