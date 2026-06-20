-- Migration 004: per-tenant token usage tracking
-- Run against existing databases (init.sql already includes this for fresh setups).

CREATE TABLE IF NOT EXISTS usage_records (
    id              BIGSERIAL   PRIMARY KEY,
    tenant_id       UUID        NOT NULL REFERENCES tenants(tenant_id),
    conversation_id UUID,
    tokens_in       INTEGER     NOT NULL DEFAULT 0,
    tokens_out      INTEGER     NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(12, 8) NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_usage_records_tenant_created
    ON usage_records (tenant_id, created_at DESC);
