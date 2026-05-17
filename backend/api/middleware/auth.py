from __future__ import annotations

from fastapi import HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from backend.config import settings

_bearer = HTTPBearer()


def _extract_api_key(token: str) -> str:
    """Return the raw API key from either a JWT or a plain API key string."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        return payload["api_key"]
    except (JWTError, KeyError):
        return token


async def get_tenant_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> str:
    api_key = _extract_api_key(credentials.credentials)

    repo = request.app.state.tenant_repo
    # repo.get_tenant_id_by_api_key hashes internally — pass the raw key
    tenant_id = await repo.get_tenant_id_by_api_key(api_key)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    return tenant_id
