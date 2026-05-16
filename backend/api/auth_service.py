from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import asyncpg
from fastapi import Cookie, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr

from backend.config import settings

app = FastAPI(title="kapa-rag auth service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

_REFRESH_COOKIE = "refresh_token"
_REFRESH_PATH = "/auth/refresh"


# ── Startup / Shutdown ────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup() -> None:
    postgres_url = settings.postgres_url.replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    app.state.pool = await asyncpg.create_pool(postgres_url, min_size=2, max_size=10)


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.pool.close()


# ── Schemas ───────────────────────────────────────────────────────────────────

class SignupRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class MeResponse(BaseModel):
    tenant_id: str
    email: str


# ── Token helpers ─────────────────────────────────────────────────────────────

def _make_access_token(tenant_id: str, api_key: str, email: str) -> str:
    """Short-lived JWT (15 min). Carries tenant_id + api_key so downstream
    services can validate without a DB lookup."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.jwt_access_expire_minutes
    )
    return jwt.encode(
        {"sub": email, "tenant_id": tenant_id, "api_key": api_key,
         "email": email, "exp": expire, "type": "access"},
        settings.jwt_secret,
        algorithm="HS256",
    )


def _make_refresh_token() -> tuple[str, str]:
    """Returns (raw_token, sha256_hash). Store only the hash in DB."""
    raw = secrets.token_urlsafe(48)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=_REFRESH_COOKIE,
        value=raw_token,
        httponly=True,          # JS cannot read it — XSS safe
        secure=False,           # set True when HTTPS is configured
        samesite="lax",
        max_age=settings.jwt_refresh_expire_days * 24 * 60 * 60,
        path=_REFRESH_PATH,     # cookie only sent to /auth/refresh
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=_REFRESH_COOKIE, path=_REFRESH_PATH)


def _decode_access_token(token: str) -> dict:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    if payload.get("type") != "access":
        raise JWTError("not an access token")
    return payload


# ── Signup ────────────────────────────────────────────────────────────────────

@app.post("/auth/signup", response_model=TokenResponse, status_code=201)
async def signup(
    body: SignupRequest, request: Request, response: Response
) -> TokenResponse:
    pool: asyncpg.Pool = request.app.state.pool

    async with pool.acquire() as conn:
        if await conn.fetchrow("SELECT 1 FROM users WHERE email = $1", body.email):
            raise HTTPException(status_code=409, detail="Email already registered")

        api_key = secrets.token_urlsafe(32)
        api_key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        password_hash = _pwd.hash(body.password)
        raw_refresh, refresh_hash = _make_refresh_token()
        refresh_expires = datetime.now(timezone.utc) + timedelta(
            days=settings.jwt_refresh_expire_days
        )

        async with conn.transaction():
            tenant = await conn.fetchrow(
                "INSERT INTO tenants (name, api_key_hash) VALUES ($1, $2) "
                "RETURNING tenant_id",
                body.email, api_key_hash,
            )
            tenant_id = str(tenant["tenant_id"])

            user = await conn.fetchrow(
                "INSERT INTO users (tenant_id, email, password_hash, api_key) "
                "VALUES ($1, $2, $3, $4) RETURNING user_id",
                tenant_id, body.email, password_hash, api_key,
            )
            user_id = str(user["user_id"])

            await conn.execute(
                "INSERT INTO refresh_tokens (token_hash, user_id, expires_at) "
                "VALUES ($1, $2, $3)",
                refresh_hash, user_id, refresh_expires,
            )

    _set_refresh_cookie(response, raw_refresh)
    return TokenResponse(
        access_token=_make_access_token(tenant_id, api_key, body.email)
    )


# ── Login ─────────────────────────────────────────────────────────────────────

@app.post("/auth/login", response_model=TokenResponse)
async def login(
    body: LoginRequest, request: Request, response: Response
) -> TokenResponse:
    pool: asyncpg.Pool = request.app.state.pool

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, tenant_id, password_hash, api_key "
            "FROM users WHERE email = $1",
            body.email,
        )

        if row is None or not _pwd.verify(body.password, row["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid email or password")

        user_id = str(row["user_id"])
        tenant_id = str(row["tenant_id"])
        raw_refresh, refresh_hash = _make_refresh_token()
        refresh_expires = datetime.now(timezone.utc) + timedelta(
            days=settings.jwt_refresh_expire_days
        )

        # Each login creates a new refresh token (supports multiple devices).
        # Optionally delete old tokens for this user to enforce single-session:
        # await conn.execute("DELETE FROM refresh_tokens WHERE user_id = $1", user_id)
        await conn.execute(
            "INSERT INTO refresh_tokens (token_hash, user_id, expires_at) "
            "VALUES ($1, $2, $3)",
            refresh_hash, user_id, refresh_expires,
        )

    _set_refresh_cookie(response, raw_refresh)
    return TokenResponse(
        access_token=_make_access_token(tenant_id, row["api_key"], body.email)
    )


# ── Refresh ───────────────────────────────────────────────────────────────────

@app.post("/auth/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
) -> TokenResponse:
    """
    Exchange a valid refresh token for a new access token.
    Rotates the refresh token on every call — old token is invalidated immediately.
    If a stolen token is used after rotation, the legitimate user's next refresh fails,
    alerting them (or your monitoring) to a potential breach.
    """
    if not refresh_token:
        raise HTTPException(status_code=401, detail="No refresh token")

    pool: asyncpg.Pool = request.app.state.pool
    token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
    now = datetime.now(timezone.utc)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT rt.user_id, rt.expires_at, u.tenant_id, u.email, u.api_key "
            "FROM refresh_tokens rt "
            "JOIN users u ON u.user_id = rt.user_id "
            "WHERE rt.token_hash = $1",
            token_hash,
        )

        if row is None:
            _clear_refresh_cookie(response)
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        if row["expires_at"] < now:
            await conn.execute(
                "DELETE FROM refresh_tokens WHERE token_hash = $1", token_hash
            )
            _clear_refresh_cookie(response)
            raise HTTPException(status_code=401, detail="Refresh token expired")

        # Rotate: delete old, insert new
        new_raw, new_hash = _make_refresh_token()
        new_expires = now + timedelta(days=settings.jwt_refresh_expire_days)

        async with conn.transaction():
            await conn.execute(
                "DELETE FROM refresh_tokens WHERE token_hash = $1", token_hash
            )
            await conn.execute(
                "INSERT INTO refresh_tokens (token_hash, user_id, expires_at) "
                "VALUES ($1, $2, $3)",
                new_hash, str(row["user_id"]), new_expires,
            )

    _set_refresh_cookie(response, new_raw)
    return TokenResponse(
        access_token=_make_access_token(
            str(row["tenant_id"]), row["api_key"], row["email"]
        )
    )


# ── Logout ────────────────────────────────────────────────────────────────────

@app.post("/auth/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
) -> None:
    """Invalidate the refresh token and clear the cookie."""
    if refresh_token:
        token_hash = hashlib.sha256(refresh_token.encode()).hexdigest()
        pool: asyncpg.Pool = request.app.state.pool
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM refresh_tokens WHERE token_hash = $1", token_hash
            )
    _clear_refresh_cookie(response)


# ── Me ────────────────────────────────────────────────────────────────────────

@app.get("/auth/me", response_model=MeResponse)
async def me(request: Request) -> MeResponse:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing token")

    try:
        payload = _decode_access_token(auth_header.removeprefix("Bearer "))
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return MeResponse(tenant_id=payload["tenant_id"], email=payload["email"])


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "auth-service"}
