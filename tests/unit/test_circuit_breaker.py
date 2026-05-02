import asyncio

import pytest

from backend.core.circuit_breaker import CircuitBreaker, CircuitOpenError, CircuitState


async def _ok() -> str:
    return "ok"


async def _fail() -> str:
    raise ValueError("boom")


async def _fallback() -> str:
    return "fallback"


class TestCircuitBreakerNormalOperation:
    async def test_closed_by_default(self):
        cb = CircuitBreaker("test")
        assert cb.state == CircuitState.CLOSED

    async def test_successful_call_returns_result(self):
        cb = CircuitBreaker("test")
        result = await cb.call(_ok)
        assert result == "ok"

    async def test_success_keeps_circuit_closed(self):
        cb = CircuitBreaker("test")
        for _ in range(10):
            await cb.call(_ok)
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerFailures:
    async def test_failure_increments_count(self):
        cb = CircuitBreaker("test", failure_threshold=5)
        with pytest.raises(ValueError):
            await cb.call(_fail)
        assert cb._failure_count == 1

    async def test_trips_open_at_threshold(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(_fail)
        assert cb.state == CircuitState.OPEN

    async def test_open_circuit_raises_without_fallback(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        with pytest.raises(ValueError):
            await cb.call(_fail)
        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitOpenError):
            await cb.call(_ok)

    async def test_open_circuit_returns_fallback_when_provided(self):
        cb = CircuitBreaker("test", failure_threshold=1)
        with pytest.raises(ValueError):
            await cb.call(_fail)

        result = await cb.call(_fail, fallback=_fallback)
        assert result == "fallback"

    async def test_failure_after_success_resets_count(self):
        cb = CircuitBreaker("test", failure_threshold=3)
        with pytest.raises(ValueError):
            await cb.call(_fail)
        await cb.call(_ok)
        assert cb._failure_count == 0
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerRecovery:
    async def test_transitions_to_half_open_after_timeout(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)
        with pytest.raises(ValueError):
            await cb.call(_fail)
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.02)

        # next call enters HALF_OPEN and probes
        result = await cb.call(_ok)
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    async def test_failed_probe_in_half_open_reopens(self):
        cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=0.01)
        with pytest.raises(ValueError):
            await cb.call(_fail)

        await asyncio.sleep(0.02)

        with pytest.raises(ValueError):
            await cb.call(_fail)
        assert cb.state == CircuitState.OPEN



























