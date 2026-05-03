-- Stores the per-tenant webhook secret used to verify GitHub push events.
-- Each tenant registers our URL + their secret in their GitHub repo settings.
CREATE TABLE IF NOT EXISTS webhook_secrets (
    tenant_id  TEXT        NOT NULL PRIMARY KEY,
    secret     TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
