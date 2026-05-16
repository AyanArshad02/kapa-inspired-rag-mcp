CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS tenants (
    tenant_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name       VARCHAR(255) NOT NULL,
    api_key_hash VARCHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT NOW(),
    is_active  BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    job_id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id),
    source_url      TEXT NOT NULL,
    source_type     VARCHAR(50) NOT NULL,
    status          VARCHAR(50) NOT NULL DEFAULT 'pending',
    docs_processed  INTEGER DEFAULT 0,
    docs_failed     INTEGER DEFAULT 0,
    error_message   TEXT,
    checkpoint      JSONB DEFAULT '{}',
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversation_turns (
    turn_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL,
    tenant_id       UUID NOT NULL REFERENCES tenants(tenant_id),
    role            VARCHAR(20) NOT NULL,
    content         TEXT NOT NULL,
    tokens          INTEGER NOT NULL,
    created_at      TIMESTAMP DEFAULT NOW()
);

ALTER TABLE ingestion_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_turns ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_jobs ON ingestion_jobs
    USING (tenant_id::text = current_setting('app.tenant_id', true));

CREATE POLICY tenant_isolation_turns ON conversation_turns
    USING (tenant_id::text = current_setting('app.tenant_id', true));

CREATE INDEX IF NOT EXISTS idx_jobs_tenant_id  ON ingestion_jobs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_jobs_status     ON ingestion_jobs(status);
CREATE INDEX IF NOT EXISTS idx_turns_conversation ON conversation_turns(conversation_id);
CREATE INDEX IF NOT EXISTS idx_turns_created   ON conversation_turns(created_at DESC);

-- source_hashes: last-seen content hash per (tenant_id, source_url).
-- Used by FreshnessManager to detect stale sources without re-fetching content.
CREATE TABLE IF NOT EXISTS source_hashes (
    tenant_id    TEXT        NOT NULL,
    source_url   TEXT        NOT NULL,
    source_type  TEXT        NOT NULL DEFAULT 'unknown',
    content_hash TEXT        NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (tenant_id, source_url)
);

CREATE INDEX IF NOT EXISTS idx_source_hashes_tenant ON source_hashes (tenant_id);

-- webhook_secrets: per-tenant HMAC secret for verifying GitHub push events.
CREATE TABLE IF NOT EXISTS webhook_secrets (
    tenant_id  TEXT        NOT NULL PRIMARY KEY,
    secret     TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
