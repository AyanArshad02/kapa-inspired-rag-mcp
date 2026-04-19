from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, TypeVar

T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(Exception):
    pass


class CircuitBreaker:
    """
    Wraps an async call and trips open after repeated failures.

    CLOSED  → normal, all calls pass through
    OPEN    → failing, calls rejected immediately (or fallback returned)
    HALF_OPEN → one probe call allowed; success → CLOSED, failure → OPEN

    One instance per external dependency (openai, cohere, qdrant)
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
    ) -> None:
        self.name = name
        self.state = CircuitState.CLOSED
        self._failure_count = 0
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._last_failure_time: float = 0.0

    async def call(
        self,
        func: Callable[..., Awaitable[T]],
        *args: Any,
        fallback: Callable[..., Awaitable[T]] | None = None,
        **kwargs: Any,
    ) -> T:
        if self.state == CircuitState.OPEN:
            if time.monotonic() - self._last_failure_time > self._recovery_timeout:
                self.state = CircuitState.HALF_OPEN
            elif fallback:
                return await fallback(*args, **kwargs)
            else:
                raise CircuitOpenError(f"Circuit '{self.name}' is OPEN")

        try:
            result = await func(*args, **kwargs)
            self._on_success()
            return result
        except Exception:
            self._on_failure()
            if fallback:
                return await fallback(*args, **kwargs)
            raise

    def _on_success(self) -> None:
        self._failure_count = 0
        self.state = CircuitState.CLOSED

    def _on_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self._failure_threshold:
            self.state = CircuitState.OPEN








