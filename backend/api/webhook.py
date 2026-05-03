from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

import asyncpg
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from pydantic import BaseModel

from backend.api.middleware.auth import get_tenant_id
from backend.config import settings
from backend.connectors.docs_connector import DocsConnector
from backend.connectors.factory import ConnectorFactory
from backend.connectors.github_connector import GitHubConnector
from backend.connectors.pdf_connector import PDFConnector
from backend.repositories.postgres_ingestion_job_repo import PostgresIngestionJobRepository
from backend.repositories.postgres_source_hash_repo import PostgresSourceHashRepository
from backend.repositories.postgres_webhook_secret_repo import PostgresWebhookSecretRepository

logger = logging.getLogger(__name__)

app = FastAPI(title="kapa-rag webhook service")


@app.on_event("startup")
async def startup() -> None:
    from backend.logging import LogSetupFactory
    LogSetupFactory.create(settings.environment).configure("webhook")

    pool = await asyncpg.create_pool(settings.postgres_url.replace("+asyncpg", ""))
    app.state.db_pool = pool
    app.state.job_repo = PostgresIngestionJobRepository(pool)
    app.state.hash_repo = PostgresSourceHashRepository(pool)
    app.state.webhook_secret_repo = PostgresWebhookSecretRepository(pool)
    logger.info("webhook service started")


@app.on_event("shutdown")
async def shutdown() -> None:
    await app.state.db_pool.close()


# ── Setup endpoint (called by dashboard) ──────────────────────────────────────

class WebhookSetupResponse(BaseModel):
    webhook_url: str
    secret: str
    instructions: str


@app.post("/webhooks/github/setup", response_model=WebhookSetupResponse)
async def setup_github_webhook(
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
) -> WebhookSetupResponse:
    """Return the tenant's webhook credentials, generating them on first call.

    The same URL + secret works for ALL of the tenant's GitHub repos —
    register it once per repo in GitHub, never need to regenerate.
    Use POST /webhooks/github/setup/rotate to explicitly get a new secret
    (requires re-registering on all repos).
    """
    existing_secret = await request.app.state.webhook_secret_repo.get(tenant_id)
    secret = existing_secret or secrets.token_hex(32)

    if not existing_secret:
        await request.app.state.webhook_secret_repo.upsert(tenant_id, secret)

    base_url = str(request.base_url).rstrip("/")
    webhook_url = f"{base_url}/webhooks/github/{tenant_id}"

    return WebhookSetupResponse(
        webhook_url=webhook_url,
        secret=secret,
        instructions=(
            f"Add this webhook to each GitHub repo you want to index.\n"
            f"The same URL + secret works for all your repos.\n"
            f"Payload URL: {webhook_url}\n"
            f"Content type: application/json\n"
            f"Secret: {secret}\n"
            f"Events: Just the push event"
        ),
    )


@app.post("/webhooks/github/setup/rotate", response_model=WebhookSetupResponse)
async def rotate_github_webhook_secret(
    request: Request,
    tenant_id: str = Depends(get_tenant_id),
) -> WebhookSetupResponse:
    """Generate a new webhook secret, invalidating the old one.

    After rotating, the tenant must update the secret in ALL their GitHub
    repos — any repo still using the old secret will start returning 401.
    """
    secret = secrets.token_hex(32)
    await request.app.state.webhook_secret_repo.upsert(tenant_id, secret)

    base_url = str(request.base_url).rstrip("/")
    webhook_url = f"{base_url}/webhooks/github/{tenant_id}"

    return WebhookSetupResponse(
        webhook_url=webhook_url,
        secret=secret,
        instructions=(
            f"Secret rotated. Update this secret in ALL your GitHub repos.\n"
            f"Payload URL: {webhook_url}\n"
            f"Content type: application/json\n"
            f"Secret: {secret}\n"
            f"Events: Just the push event"
        ),
    )


# ── GitHub push webhook ────────────────────────────────────────────────────────

@app.post("/webhooks/github/{tenant_id}")
async def github_push_webhook(
    tenant_id: str,
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
) -> dict:
    """Receive a GitHub push event and incrementally re-index changed files.

    tenant_id is in the URL path — no API key needed.
    Authenticity is proved by HMAC-SHA256 signature using the per-tenant secret.
    """
    body = await request.body()

    stored_secret = await request.app.state.webhook_secret_repo.get(tenant_id)
    if not stored_secret:
        raise HTTPException(status_code=404, detail="No webhook configured for this tenant")

    _verify_signature(body, x_hub_signature_256, stored_secret)

    payload = await request.json()

    # GitHub sends a ping event when the webhook is first registered — just acknowledge it
    if "zen" in payload:
        return {"status": "pong"}

    repo_url = payload.get("repository", {}).get("html_url", "")
    if not repo_url:
        raise HTTPException(status_code=422, detail="Missing repository.html_url in payload")

    fm = _build_freshness_manager(request)
    await fm.handle_github_push(tenant_id, repo_url, payload)

    commits = payload.get("commits", [])
    changed = sum(
        len(c.get("added", [])) + len(c.get("modified", [])) + len(c.get("removed", []))
        for c in commits
    )
    logger.info("webhook: tenant=%s repo=%s changed_files=%d", tenant_id, repo_url, changed)
    return {"status": "accepted", "changed_files": changed}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_freshness_manager(request: Request):
    from backend.core.freshness_manager import FreshnessManager
    from backend.strategies.embedding.openai_embedding import OpenAIEmbedding
    from backend.strategies.embedding.tf_sparse_encoder import TFSparseEncoder
    from backend.strategies.vectordb.qdrant_db import QdrantDB

    factory = ConnectorFactory()
    factory.register(DocsConnector())
    factory.register(PDFConnector())
    factory.register(GitHubConnector())

    return FreshnessManager(
        connector_factory=factory,
        hash_repo=request.app.state.hash_repo,
        job_repo=request.app.state.job_repo,
        embedder=OpenAIEmbedding(),
        sparse_encoder=TFSparseEncoder(),
        vector_db=QdrantDB(),
    )


def _verify_signature(body: bytes, signature_header: str | None, secret: str) -> None:
    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing or malformed X-Hub-Signature-256")

    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
