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

-- users: one row per signup. Stores email/password and the raw API key so
-- it can be embedded in a JWT on login without requiring the user to copy it.
CREATE TABLE IF NOT EXISTS users (
    user_id       UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id     UUID        NOT NULL REFERENCES tenants(tenant_id),
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    api_key       TEXT        NOT NULL,
    is_admin      BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);

-- refresh_tokens: one row per active session. Token is stored as SHA-256 hash.
-- On each refresh the old token is deleted and a new one is issued (rotation).
CREATE TABLE IF NOT EXISTS refresh_tokens (
    token_hash  TEXT        PRIMARY KEY,
    user_id     UUID        NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens (user_id);

-- webhook_secrets: per-tenant HMAC secret for verifying GitHub push events.
CREATE TABLE IF NOT EXISTS webhook_secrets (
    tenant_id  TEXT        NOT NULL PRIMARY KEY,
    secret     TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
