from __future__ import annotations

from collections.abc import AsyncIterator

from openai import APIError, APITimeoutError, AsyncOpenAI, RateLimitError

from backend.config import settings
from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError
from backend.core.pricing import get_cost
from backend.exceptions import LLMInvalidResponseError, LLMRateLimitError, LLMTimeoutError
from backend.models import ContextWindow, QueryResult
from backend.strategies.base import LLMStrategy
from backend.strategies.llm._prompts import build_messages


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
        messages = build_messages(context)
        model = _select_model(context)

        try:
            response = await self._circuit.call(
                self._client.chat.completions.create,
                model=model,
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

        if response.usage:
            context.tokens_in = response.usage.prompt_tokens
            context.tokens_out = response.usage.completion_tokens
            context.cost_usd = get_cost(model, context.tokens_in, context.tokens_out)

        return QueryResult(
            answer=response.choices[0].message.content or "",
            source_chunks=context.chunks,
        )

    async def generate_stream(self, context: ContextWindow) -> AsyncIterator[str]:
        messages = build_messages(context)
        model = _select_model(context)

        try:
            # Circuit breaker covers the initial connection; iteration happens outside it
            stream = await self._circuit.call(
                self._client.chat.completions.create,
                model=model,
                messages=messages,
                temperature=0.1,
                max_tokens=1024,
                stream=True,
                stream_options={"include_usage": True},
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
                if chunk.usage:
                    context.tokens_in = chunk.usage.prompt_tokens
                    context.tokens_out = chunk.usage.completion_tokens
                    context.cost_usd = get_cost(
                        model, context.tokens_in, context.tokens_out
                    )
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except APIError as exc:
            raise LLMInvalidResponseError(f"Stream interrupted: {exc}") from exc
