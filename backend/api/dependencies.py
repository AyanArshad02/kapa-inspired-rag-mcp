from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status

from backend.api.middleware.auth import get_tenant_id
from backend.config import settings
from backend.core.rate_limiter import check_rate_limit
from backend.observers.metrics_observer import rate_limit_hits_total


async def rate_limit(
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
) -> None:
    allowed, _, limit = await check_rate_limit(
        request.app.state.redis,
        tenant_id,
        settings.rate_limit_per_minute,
    )
    if not allowed:
        rate_limit_hits_total.labels(tenant_id=tenant_id).inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Rate limit exceeded",
                "tenant_id": tenant_id,
                "limit": limit,
                "window": "1 minute",
                "hint": "Reduce request frequency or contact support to increase your limit.",
            },
            headers={"Retry-After": "60"},
        )
