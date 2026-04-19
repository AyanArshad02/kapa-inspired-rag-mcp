from __future__ import annotations

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

_bearer = HTTPBearer()


async def get_tenant_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    api_key = credentials.credentials
    repo = request.app.state.tenant_repo

    tenant_id = await repo.get_tenant_id_by_api_key(api_key)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return tenant_id







