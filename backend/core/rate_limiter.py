from __future__ import annotations

import time

import redis.asyncio as aioredis


async def check_rate_limit(
    redis: aioredis.Redis,
    tenant_id: str,
    limit: int,
    window_seconds: int = 60,
) -> tuple[bool, float, int]:
    """
    Sliding window counter rate limiter.

    Uses two fixed window counters (current + previous) and linear interpolation
    to estimate the true request count in the last `window_seconds`.

    Returns (allowed, estimated_count, limit).
    """
    now = time.time()
    current_window = int(now) // window_seconds
    previous_window = current_window - 1

    current_key = f"rate_limit:{tenant_id}:{current_window}"
    previous_key = f"rate_limit:{tenant_id}:{previous_window}"

    # Single round-trip: read previous count, increment current, refresh TTL.
    # TTL = window_seconds * 2 so the previous-window key is still readable
    # in the next window before natural expiry.
    pipe = redis.pipeline()
    pipe.get(previous_key)
    pipe.incr(current_key)
    pipe.expire(current_key, window_seconds * 2)
    results = await pipe.execute()

    prev_count = int(results[0] or 0)
    current_count = int(results[1])

    elapsed = now - (current_window * window_seconds)
    weight_of_prev = 1.0 - (elapsed / window_seconds)
    estimated = current_count + prev_count * weight_of_prev

    return estimated <= limit, estimated, limit



