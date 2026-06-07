from __future__ import annotations

import logging

import asyncpg
from fastapi import APIRouter, Depends, Request

from backend.api.middleware.auth import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])

_SOURCE_TYPE_LABELS = {
    "docs_site": "Documentation",
    "github": "GitHub repo",
    "pdf": "PDF",
    "slack": "Slack",
}


@router.get("/overview")
async def overview(request: Request) -> dict:
    """System-wide stats across all tenants. Admin only."""
    pool: asyncpg.Pool = request.app.state.db_pool

    async with pool.acquire() as conn:
        totals = await conn.fetchrow(
            """
            SELECT
                (SELECT COUNT(*)  FROM tenants           WHERE is_active = TRUE)  AS total_tenants,
                (SELECT COUNT(*)  FROM users)                                      AS total_users,
                (SELECT COUNT(*)  FROM source_hashes)                             AS total_sources,
                (SELECT COUNT(*)  FROM conversation_turns WHERE role = 'user')    AS total_queries
            """
        )

        tenant_rows = await conn.fetch(
            """
            SELECT
                t.tenant_id,
                t.name,
                u.email,
                u.is_admin,
                COUNT(DISTINCT sh.source_url)       AS source_count,
                COUNT(DISTINCT ct.conversation_id)  AS conversation_count,
                COALESCE(SUM(CASE WHEN ct.role = 'user' THEN 1 ELSE 0 END), 0) AS query_count
            FROM tenants t
            LEFT JOIN users           u  ON u.tenant_id  = t.tenant_id
            LEFT JOIN source_hashes   sh ON sh.tenant_id = t.tenant_id::text
            LEFT JOIN conversation_turns ct ON ct.tenant_id = t.tenant_id
            WHERE t.is_active = TRUE
            GROUP BY t.tenant_id, t.name, u.email, u.is_admin
            ORDER BY query_count DESC
            """
        )

        recent_queries = await conn.fetch(
            """
            SELECT ct.content, ct.tenant_id::text, ct.created_at, t.name AS tenant_name
            FROM   conversation_turns ct
            JOIN   tenants t ON t.tenant_id = ct.tenant_id
            WHERE  ct.role = 'user'
            ORDER  BY ct.created_at DESC
            LIMIT  20
            """
        )

        sources_by_type = await conn.fetch(
            """
            SELECT source_type, COUNT(*) AS count
            FROM   source_hashes
            GROUP  BY source_type
            ORDER  BY count DESC
            """
        )

    return {
        "totals": {
            "tenants": totals["total_tenants"],
            "users": totals["total_users"],
            "sources": totals["total_sources"],
            "queries": totals["total_queries"],
        },
        "tenants": [
            {
                "tenant_id": str(r["tenant_id"]),
                "name": r["name"],
                "email": r["email"],
                "is_admin": r["is_admin"],
                "source_count": r["source_count"],
                "conversation_count": r["conversation_count"],
                "query_count": r["query_count"],
            }
            for r in tenant_rows
        ],
        "recent_queries": [
            {
                "content": r["content"][:120],
                "tenant_name": r["tenant_name"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in recent_queries
        ],
        "sources_by_type": [
            {
                "type": _SOURCE_TYPE_LABELS.get(r["source_type"], r["source_type"]),
                "count": r["count"],
            }
            for r in sources_by_type
        ],
    }
