-- Stores the last-seen content hash per (tenant_id, source_url).
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
