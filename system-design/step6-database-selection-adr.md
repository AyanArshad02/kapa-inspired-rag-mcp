# Step 6 — Database Selection ADR

ADR = Architectural Decision Record. Every database choice here
follows the same framework:

Classify the data first → apply CAP theorem → choose the DB →
document what breaks if this decision is wrong → define the
trigger to revisit it.

We never choose a database because it is popular. We choose it
because the data's characteristics demand it.

---

## THE 9-STEP FRAMEWORK APPLIED TO EVERY DATASET

For each dataset we ask:
1. Is this source of truth or derived data?
2. Can we rebuild it if lost?
3. Does loss cause financial or legal damage?
4. What is the access pattern? (key lookup vs complex query)
5. Read heavy or write heavy?
6. ACID or BASE acceptable?
7. CP or AP under partition?
8. What is the latency requirement?
9. How painful is it to migrate away from this DB later?

---

## DATASET 1: Tenant and API Key Data

What it stores:
  tenant_id, name, plan, created_at
  api_key_hash, tenant_id, scopes, created_at, revoked_at

Classification: Source of truth
  Loss impact: Every query breaks — cannot derive tenant_id
  from anything else. Cannot rebuild if lost.
  Financial damage: Yes — billing and access control depend on this.

Access pattern:
  API key lookup on every single request → derive tenant_id
  Point lookup by api_key_hash
  Occasional admin reads (list tenants, update plan)
  Low write volume (new tenant onboarding is rare)

Consistency requirement: STRONG
  Two requests with the same API key must always get the same
  tenant_id. Even 1 second of staleness here is unacceptable —
  it could route a query to the wrong namespace.

CAP choice: CP
  During network partition → reject requests rather than serve
  wrong tenant mapping. Correctness over availability here.

ACID requirement: YES
  Creating a new tenant requires:
    INSERT into tenants
    INSERT into api_keys
  Both must succeed or both must roll back. If api_key is created
  without a tenant record, the system is in an inconsistent state.

Database: PostgreSQL (RDS)
WHY:
  ACID transactions across tenant + api_key tables
  Row Level Security (RLS) enforced at DB layer
  Simple schema, low write volume — RDS handles this trivially
  Already in the stack — no extra service

Migration pain: HIGH
  Every other service depends on this. Therefore we need to get it right from day one.
  tenant_id column in every table from day one
  this later is a multi-million-row migration done at 3am.

REVISIT TRIGGER: Never. PostgreSQL is the right permanent home for this data.

---

## DATASET 2: Conversation History

What it stores:
  session_id, tenant_id, role (user/assistant), content,
  tokens, created_at, expires_at

Classification: Semi-derived
  Loss impact: User loses last 3 turns of context. Annoying
  but not major disaster. Cannot cause financial damage.
  Rebuildable: No (conversation content cannot be reconstructed)
  but losing it does not break the system.

Access pattern:
  Always fetched by session_id → get last 3 turns
  Append-only (new turn added after each query)
  Never joins, never aggregations
  Read and written on every single query

Consistency requirement: EVENTUAL acceptable
  If conversation history is 1 second stale, the user does not
  notice. AP is fine here.

CAP choice: AP in theory — but we choose PostgreSQL anyway.
  Here is why:

  DynamoDB would be the textbook AP choice for this access
  pattern. But at our scale (10,000 queries/day), PostgreSQL
  handles this with zero strain. We are already running it
  for tenant data. Adding DynamoDB here adds:
    - $50-100/month extra cost (personal project budget matters)
    - Another AWS service to configure and debug
    - Eventual consistency complexity for zero benefit

  PostgreSQL with a session_id index gives us sub-10ms reads
  on this table at our scale. That is faster than DynamoDB
  cold reads in some cases.

Database: PostgreSQL (RDS) — same instance as tenant data
WHY:
  Already in the stack
  Simple key-value lookup by session_id (index handles it)
  At 10,000 queries/day, write throughput is 0.12 writes/sec
  — PostgreSQL handles 1,000+ writes/sec easily
  No extra cost, no extra ops burden

Schema:
  conversation_turns (
    id          BIGSERIAL PRIMARY KEY,
    session_id  UUID NOT NULL,
    tenant_id   UUID NOT NULL,
    role        VARCHAR(10) NOT NULL, -- 'user' | 'assistant'
    content     TEXT NOT NULL,
    tokens      INT,
    created_at  TIMESTAMP DEFAULT NOW()
  )
  INDEX: idx_session_turns (session_id, created_at DESC)
  RLS: tenant_id enforced at DB layer

Sessions table:
  sessions (
    session_id  UUID PRIMARY KEY,
    tenant_id   UUID NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW(),
    expires_at  TIMESTAMP NOT NULL -- 1 hour TTL
  )

REVISIT TRIGGER: If conversation history write throughput
  exceeds 500 writes/sec sustained (happens at ~250M queries/day), migrate to DynamoDB.
  Repository pattern on data access layer makes this a config change not a rewrite.

B2B SaaS consideration: At 1,000 tenants and millions of
  queries/day, DynamoDB becomes the right choice. Partition
  key: session_id. Access pattern is perfect for DynamoDB
  at that scale. Migration path is clean because the
  Repository pattern abstracts the storage layer.

---

## DATASET 3: Ingestion Job Tracking

What it stores:
  job_id, tenant_id, source_url, source_type, status,
  docs_processed, docs_failed, error_message,
  created_at, completed_at

Classification: Operational metadata
  Loss impact: Lose visibility into job status. Jobs themselves
  are idempotent — can be re-triggered. Not catastrophic.

Access pattern:
  INSERT on job creation
  UPDATE on status change (pending → running → completed/failed)
  GET by job_id (tenant admin polling status)
  Occasional LIST by tenant_id (admin dashboard)

Consistency requirement: STRONG for status transitions
  A job must not appear both "running" and "completed"
  simultaneously. Concurrent status updates must be atomic.

CAP choice: CP
Database: PostgreSQL (RDS) — same instance
WHY:
  Status transitions need ACID (atomic UPDATE with WHERE clause)
  Low volume (43 jobs/day at 1-year scale — negligible)
  Already in the stack

Schema:
  ingestion_jobs (
    job_id          UUID PRIMARY KEY,
    tenant_id       UUID NOT NULL,
    source_url      TEXT,
    source_type     VARCHAR(20), -- 'docs'|'github'|'pdf'|'slack'
    status          VARCHAR(20) NOT NULL, -- 'pending'|'running'|
                                         -- 'completed'|'failed'
    docs_processed  INT DEFAULT 0,
    docs_failed     INT DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMP DEFAULT NOW(),
    completed_at    TIMESTAMP
  )
  INDEX: idx_jobs_tenant (tenant_id, created_at DESC)

REVISIT TRIGGER: Never. This table stays small forever.

---

## DATASET 4: Vector Embeddings (Knowledge Base)

What it stores:
  Dense vector (1536 dims), sparse vector (SPLADE format),
  metadata: source_url, document_title, chunk_index,
  tenant_id, source_type, timestamp, version

Classification: Derived data
  Loss impact: Knowledge base goes offline until re-indexed.
  Fully rebuildable from S3 (raw docs are source of truth).
  No financial damage — just operational disruption.

Access pattern:
  Hybrid similarity search (dense + sparse, parallel to reduce latency as compared to sequential search)
  Always filtered by tenant namespace
  High read volume (every query hits Qdrant)
  Batch writes during ingestion (not real-time)
  Never point lookups, never joins

Consistency requirement: EVENTUAL acceptable
  24-hour staleness is fine. If a new doc is indexed, it
  appearing in search results after a few seconds delay
  is completely acceptable.

CAP choice: AP
  During partition → serve queries from existing index.
  Slightly stale results are infinitely better than downtime.

Database: Qdrant (self-hosted on EC2)
WHY:
  Native hybrid search (dense + sparse in one query call)
  Dense and sparse retrieved in parallel internally
  RRF fusion built into Qdrant — no custom merge code
  One collection per tenant = hard isolation at DB layer
  Metadata filtering per tenant on every query
  Self-hosted = zero extra cost at our scale
  32GB RAM on r6g.xlarge handles 100 tenants comfortably

Alternative considered: Pinecone (managed)
  Pros: Zero ops, 99.9% SLA, auto-scaling
  Cons: $70-200/month minimum, vendor lock-in
  Decision: Self-hosted Qdrant at personal project scale.
  Strategy pattern on VectorDBStrategy means switching to
  Pinecone is a one-line config change if ops burden grows.

Collection design:
  One Qdrant collection per tenant:
    collection name: tenant_{tenant_id}
  Each point:
    id: chunk_uuid
    vector: { dense: [...1536 floats], sparse: {idx: weight} }
    payload: {
      source_url: string,
      document_title: string,
      chunk_index: int,
      tenant_id: string,
      source_type: string, -- 'docs'|'github'|'pdf'|'slack'
      content: string,     -- original chunk text
      timestamp: string,
      version: string
    }

Why one collection per tenant vs shared collection + filter:
  Shared collection: cheaper RAM, but metadata filter on every
    query adds latency and risks cross-tenant leakage if filter
    is ever missing (one bug = data leak)
  One collection per tenant: slightly more RAM overhead but
    isolation is guaranteed at the DB layer. A missing filter
    cannot leak data because the collection itself belongs to
    one tenant only.
  Decision: one collection per tenant. Safety over marginal
    RAM savings. At 100 tenants × 325MB = 32GB — manageable.

REVISIT TRIGGER: When total vector storage exceeds 60GB
  (roughly 185 tenants), upgrade to r6g.2xlarge (64GB).
  When total exceeds 160GB (500+ tenants), implement Qdrant
  sharding by tenant_id range.

---

## DATASET 5: Raw Documents

What it stores:
  Original fetched content before chunking.
  Path: s3://bucket/tenant-{id}/docs/{doc_hash}/{version}

Classification: Source of truth for embeddings
  Loss impact: Cannot rebuild vector index if this is lost.
  This is the master copy. Everything else is derived from it.

Access pattern:
  Write once on ingestion (or on update)
  Read during re-indexing jobs (not in query path)
  Never queried directly by users
  Sequential reads during batch re-index

Consistency requirement: STRONG for writes
  Once a doc is written to S3, it must be there. No eventual
  consistency on writes — we need S3's synchronous PUT
  confirmation before marking the ingestion job as complete.

CAP choice: CP for writes, AP for reads (S3 default behavior)
Database: AWS S3
WHY:
  11 nines durability (99.999999999%)
  Infinite scale — never worry about storage capacity
  Versioning enabled — keeps last 3 versions of every doc
  Essentially free at our scale (~$2/month for 75GB)
  Decoupled from query path — S3 slowness never affects queries
  Cross-region replication available if needed later

Path convention:
  s3://kapa-rag-docs/tenant-{tenant_id}/
                       {source_type}/
                         {doc_hash}/
                           {version}/
                             raw.{ext}

REVISIT TRIGGER: Never. S3 is the permanent home for raw docs.

---

## DATASET 6: Cache (Query Responses + Rate Limits)

What it stores:
  Response cache: query hash → full response JSON (TTL: 1hr)
  Rate limits: tenant_id + window → request count (TTL: 60s)
  Celery job queue: pending ingestion job payloads

Classification: Disposable / Derived
  Loss impact: Cache miss → query runs through full pipeline
  (slower but correct). Rate limits reset → temporary over-quota
  risk (acceptable for brief Redis restart). Queue loss →
  in-flight ingestion jobs need re-triggering (mitigated by
  Celery's retry logic and job status in PostgreSQL).

Access pattern:
  Sub-millisecond reads on every query (cache check)
  Atomic INCR on every request (rate limiting)
  LPUSH/RPOP for Celery job queue
  All key-value, no joins, no aggregations

Consistency requirement:
  Cache: none (stale cache is fine, just a miss)
  Rate limiting: STRONG (must be atomic to prevent quota bypass)
  Queue: eventual (Celery handles retry)

CAP choice: AP for cache, CP for rate limit counters
  Redis atomic INCR is always consistent within a single
  Redis instance. No partition tolerance issues at our scale
  (single Redis instance).

Database: Redis (self-hosted on same EC2 as other services)
WHY:
  Sub-millisecond reads and writes
  Native TTL on every key (no cleanup jobs needed)
  Atomic INCR for rate limiting (no race conditions)
  Already the Celery broker — one service, three jobs
  At our scale, a single Redis instance handles everything

Key patterns:
  cache:{tenant_id}:{sha256(query)}  → response JSON, TTL 3600s
  ratelimit:{tenant_id}:{minute}     → count, TTL 60s
  celery queue keys                  → managed by Celery

B2B SaaS upgrade: ElastiCache (managed Redis)
  When Redis availability becomes critical (paying customers
  depend on cache hit rates), move to ElastiCache with
  Multi-AZ replication. Same Redis interface — zero code change.

REVISIT TRIGGER: When Redis availability > 99.9% becomes a
  hard requirement. Move to ElastiCache at that point.

---

## FULL DATABASE SELECTION SUMMARY

Dataset                | Database      | CAP | ACID | Why
-----------------------|---------------|-----|------|----
Tenants + API keys     | PostgreSQL    | CP  | YES  | Source of truth, auth critical
Conversation history   | PostgreSQL    | AP* | NO   | Already in stack, scale fine
Ingestion job tracking | PostgreSQL    | CP  | YES  | Status transitions need ACID
Vector embeddings      | Qdrant        | AP  | NO   | Similarity search, derived
Raw documents          | S3            | CP  | NO   | Source of truth, 11 nines
Response cache         | Redis         | AP  | NO   | Disposable, sub-ms required
Rate limiting          | Redis (atomic)| CP  | NO   | Must be exact, atomic INCR
Celery job queue       | Redis         | AP  | NO   | Disposable, retry handles loss

*PostgreSQL chosen over DynamoDB for conversation history
because at our scale it is more than sufficient and already
in the stack. DynamoDB becomes correct at 1M+ queries/day.

---

## THE GOLDEN RULE APPLIED

Every database decision above followed this order:

1. Classify the data (source of truth vs derived vs cache)
2. Identify consistency requirement (strong vs eventual)
3. Apply CAP theorem (CP vs AP under partition)
4. Check if ACID is needed (transactions across tables?)
5. Check access pattern (key lookup vs query vs similarity)
6. Check scale (does PostgreSQL handle it? only move away if forced)
7. Check cost (personal project — avoid extra services if unnecessary)
8. Document migration pain and revisit trigger

The result: PostgreSQL for everything relational and transactional,
Qdrant for vectors, S3 for raw storage, Redis for speed.
Simple, well-understood stack. No exotic databases. Every choice
is justified by data characteristics.




