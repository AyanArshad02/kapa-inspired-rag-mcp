# Step 8 — Pre-mortem

A pre-mortem is the opposite of a post-mortem. Instead of
asking "what went wrong" after the system fails, we ask
"imagine it is 6 months from now and this system has failed
badly — what killed it?" then work backwards to prevent it.

This is not a list of theoretical risks. Every failure mode
here is grounded in how RAG systems actually break in
production.

Format: Failure → Root Cause → Probability → Impact →
Prevention → Detection

---

## FAILURE 1: Faithfulness Silently Degrades Below 0.85

### What happens
Users start getting confidently wrong answers. They stop
trusting the system. Churn follows. Nobody files a bug report
— they just quietly stop using it. By the time you notice,
the damage is done.

### Root cause
One of three things kills faithfulness silently:

1. LLM provider updates their model without announcement.
   GPT-4o behavior changes subtly. Your grounding prompt
   that worked last month now produces slightly different
   citation patterns. Faithfulness drops from 0.91 to 0.78
   over two weeks and nobody notices.

2. Chunk quality degrades. A docs site restructures its HTML.
   Your crawler still runs, but now it is ingesting nav menus,
   footers, and boilerplate as chunks. Retrieval now surfaces
   garbage chunks. LLM has no good context to ground answers
   in. Hallucination rate climbs.

3. Context window overflow. As tenants add more documents,
   average chunk count increases. Token budget overflows
   silently, lowest-ranked chunks are dropped, LLM loses
   key context. Nobody changed any code — the system just
   got worse as it got more data.

### Probability: HIGH
This has happened to every production RAG system we know of.
It is a when, not an if.

### Impact: CRITICAL
Trust is the only product. Once users learn not to trust
the answers, no performance fix brings them back.

### Prevention
Continuous evaluation pipeline — non-negotiable:
  Golden dataset of 100+ query-answer pairs per tenant
  RAGAS evaluation runs after every deployment
  RAGAS evaluation runs on a weekly schedule even with
  no deployments (catches model drift)
  Deployment gate: faithfulness < 0.85 blocks deploy
  Alerting: if weekly eval drops > 5% from baseline,
  PagerDuty fires

Model version pinning:
  Never use unpinned model versions in production
  claude-3-5-sonnet-20241022 not claude-3-5-sonnet-latest
  New model versions tested in shadow mode on 10% traffic
  before promoting to 100%

Chunk quality monitoring:
  Log average chunk token count per ingestion job
  Alert if average drops below 100 tokens (boilerplate
  indicator) or exceeds 1,200 tokens (chunker breaking)
  Spot-check 5 random chunks per ingestion job in logs

### Detection
Weekly automated RAGAS run with Grafana trend chart
Alert threshold: faithfulness drops 5% week-over-week
LangSmith trace sampling: review 10 random traces per day

---

## FAILURE 2: One Tenant's Bulk Upload Kills Everyone's Queries

### What happens
A tenant uploads their entire documentation site — 2,000
docs at once. Celery workers get saturated processing the
embedding jobs. If indexing and query pipelines are not
properly separated, query latency spikes from 500ms to 8s
for every other tenant. Users see timeouts. They report the
system is broken.

### Root cause
Pipeline separation not enforced at the resource level.
Celery workers handling ingestion consume all available CPU
and memory. Query service is starved.

OR

Celery worker pool is sized too small. 3 workers is fine
for 43 jobs/day. But if 5 tenants simultaneously trigger
full re-index, that is 25,000 documents hitting the queue
at once. 3 workers take 16+ hours to clear the backlog.
Tenants see stale knowledge bases and open support tickets.

### Probability: MEDIUM at launch, HIGH at 30+ tenants

### Impact: HIGH
Every tenant is affected, not just the one uploading.
Multi-tenant blast radius.

### Prevention
Hard separation between ingestion and query processes:
  Query service (FastAPI :8000) and Celery workers are
  separate Docker containers with separate resource limits
  set in docker-compose.yml
  Celery workers cannot consume query service CPU — OS-level
  process isolation

Resource limits in Docker Compose:
  query-service:   cpus: 2.0, memory: 4GB
  celery-worker:   cpus: 1.5, memory: 3GB
  These limits ensure ingestion never starves queries

Ingestion rate limiting per tenant:
  Max 1 active ingestion job per tenant at a time
  Concurrent job check on POST /ingest — reject if tenant
  already has a running job
  Queue depth alert: if queue > 50 jobs, alert and
  consider spinning up additional Celery workers

### Detection
Prometheus metric: celery_queue_depth
Alert: queue depth > 20 for more than 10 minutes
Prometheus metric: query_p95_latency
Alert: p95 latency > 3s for more than 2 minutes

---

## FAILURE 3: Qdrant RAM Exhaustion Causes OOM Kills

### What happens
Tenants grow their knowledge bases. Qdrant loads more vectors
into RAM. At some point the EC2 instance runs out of memory.
Linux OOM killer fires. Qdrant process is killed. Query
service starts returning 500s. System is effectively down.

This happens silently and suddenly — no graceful degradation,
just a hard crash.

### Root cause
Qdrant's HNSW index is memory-mapped — it keeps the index
in RAM for fast search. At 100 tenants × 325MB = 32GB, a
t3.xlarge (16GB) is completely insufficient. Even our target
r6g.xlarge (32GB) has zero headroom if tenants grow their
doc count beyond estimates.

We planned for 5,000 docs per tenant × 10 chunks × 6.5KB
= 325MB per tenant. But what if a tenant has 15,000 docs?
That is 975MB for one tenant. 30 such tenants = 29GB. One
large tenant could unexpectedly push us over the edge.

### Probability: MEDIUM (if we do not monitor proactively)

### Impact: CRITICAL
Qdrant OOM = full system outage. No fallback for vector
search at scale (BM25 fallback is last resort, not a real
substitute for semantic search).

### Prevention
Per-tenant document limits enforced at ingestion:
  Default limit: 10,000 documents per tenant
  Hard reject on POST /ingest if tenant exceeds limit
  Limit is configurable per tenant in PostgreSQL (enterprise
  tenants can get higher limits)

Qdrant RAM monitoring — proactive, not reactive:
  Prometheus scrapes Qdrant /metrics endpoint
  Alert at 60% RAM usage: "plan upgrade"
  Alert at 80% RAM usage: "urgent — upgrade within 24hrs"
  Alert at 90% RAM usage: "critical — upgrade immediately"

EC2 upgrade path is pre-planned:
  t3.xlarge (16GB) → r6g.large (16GB, memory optimized)
    → r6g.xlarge (32GB) → r6g.2xlarge (64GB)
  All Qdrant upgrades: snapshot → new instance → restore
  → verify → swap DNS. Target: < 30 minutes RTO.

### Detection
Prometheus metric: qdrant_memory_used_bytes
Grafana alert: memory_used / memory_total > 0.60
Node exporter: EC2 instance memory usage as secondary signal

---

## FAILURE 4: OpenAI Rate Limits or Outage During Peak Usage

### What happens
OpenAI has a service incident. All LLM calls start returning
429 (rate limit) or 500 (service error). Every query in
the system fails at the LLM generation step. Users get
errors. If we have no fallback, the system is completely
broken for the duration of the incident.

OpenAI has had multiple multi-hour incidents in the past.
This is not a theoretical risk.

### Root cause
Single LLM provider with no fallback. Circuit breaker not
configured. Retry storm — every failing request retries
immediately, amplifying load on an already struggling
provider.

### Probability: HIGH (OpenAI incidents happen regularly)

### Impact: HIGH if no fallback, LOW if fallback is in place

### Prevention
Circuit breaker on all OpenAI calls:
  Opens after 5 failures in 60 seconds
  While open: return retrieved chunks to user without
  LLM generation — "Here are the most relevant docs I
  found. LLM generation is temporarily unavailable."
  This is not a great experience but it is infinitely
  better than a blank error
  Half-open after 60 seconds: test one request
  Resume normal operation on success

Exponential backoff on retries:
  First retry: 1 second
  Second retry: 2 seconds
  Third retry: 4 seconds
  After 3 retries: circuit opens, fallback activates
  Never blind immediate retries — they amplify the problem

LLMStrategy makes provider switching fast:
  If OpenAI is down for more than 30 minutes, we can
  switch LLM_PROVIDER=claude in .env and restart the
  query service in under 5 minutes
  This is a manual failover — not automated in v1
  Automation (automatic provider failover) is v2

Rate limit prevention:
  Semaphore limits concurrent OpenAI calls to 20
  This prevents us from hitting rate limits ourselves
  during traffic spikes

### Detection
Prometheus metric: llm_error_rate (5xx + 429 responses)
Alert: error_rate > 10% for more than 2 minutes
LangSmith: traces show which step is failing
OpenAI status page webhook → Slack notification

---

## FAILURE 5: Cross-Tenant Data Leakage

### What happens
A bug in the application layer causes one tenant's query
to retrieve chunks from another tenant's knowledge base.
Company A's internal API docs leak to Company B. This is
the single most catastrophic failure mode for a multi-tenant
system. It is not recoverable — the damage is done the moment
the data is served.

### Root cause
Application code passes wrong tenant_id to Qdrant query.
Missing filter on a code path. A refactor removes a tenant
scope somewhere and tests do not catch it.

OR

A developer accidentally puts two tenants' documents in the
same Qdrant collection during setup, so filtering is not
enough.

### Probability: LOW if isolated at DB layer, MEDIUM if only
isolated at application layer

### Impact: CATASTROPHIC
Legal liability. Permanent trust destruction. System shutdown.

### Prevention
Isolation at the DB layer, not the application layer:
  Each tenant has their own Qdrant collection (tenant_{id})
  Even if application code passes the wrong tenant_id,
  the collection itself belongs to exactly one tenant
  A missing filter cannot leak data because the collection
  is the boundary, not a WHERE clause

PostgreSQL RLS on every table:
  Even if application code forgets WHERE tenant_id = X,
  RLS at the DB layer enforces it automatically
  Test RLS with a dedicated test that attempts cross-tenant
  reads and asserts they fail

S3 bucket policies per tenant prefix:
  IAM policies restrict read/write to own prefix only

Automated cross-tenant leak tests:
  Part of CI/CD pipeline — not optional
  Test: create two tenants, ingest docs for each, query
  as tenant A, assert zero chunks from tenant B appear
  This test runs on every pull request

Code review checklist item:
  Every PR that touches query or retrieval logic requires
  explicit reviewer sign-off that tenant scoping is correct

### Detection
Automated cross-tenant test in CI (primary defense)
Manual penetration test before any public launch
Log analysis: flag any query response that contains
chunk metadata from a different tenant_id than the
requesting tenant

---

## FAILURE 6: Incremental Re-index Misses Deleted Content

### What happens
A tenant deletes a page from their docs site. The incremental
re-index only processes new and changed documents — it does
not detect deletions. The deleted content stays in the Qdrant
index indefinitely. Users keep getting answers based on
deprecated or removed documentation. They get confused.
Support tickets increase. Nobody knows why the AI is giving
outdated answers because the system appears to be working.

### Root cause
Incremental re-index by nature cannot detect what was removed.
It only sees what is there, not what used to be there.

This is one of kapa.ai's documented #1 silent failure modes.
They call it "ghost content." It is invisible until a user
notices the AI citing a page that returns 404.

### Probability: HIGH (docs sites delete and restructure
content constantly)

### Impact: MEDIUM — does not break the system, but silently
degrades answer quality and user trust over time

### Prevention
Weekly full re-index is non-negotiable:
  Celery Beat triggers full re-index every Sunday at 2am
  Full re-index: crawl all sources, compare against current
  Qdrant index, delete chunks whose source URLs no longer
  exist, re-embed changed content
  This is the only reliable way to handle deletions

Document URL fingerprinting:
  Every chunk's source_url is stored in Qdrant metadata
  During full re-index, fetch current sitemap URL list
  Any URL in Qdrant metadata that is no longer in the
  sitemap → mark for deletion → batch delete from Qdrant
  This makes deletion detection explicit and auditable

Deletion log:
  Every deleted chunk is logged with: tenant_id, source_url,
  chunk_id, deletion_timestamp, reason (not_in_sitemap)
  Tenant admins can query this log via GET /ingest/deletions

### Detection
Compare chunk count before and after each full re-index
Alert if chunk count drops > 20% in one full re-index
(could indicate crawler failure, not just deletions)
Log: deleted_chunks_count per re-index job

---

## FAILURE 7: MCP Server Connection Instability

### What happens
Cursor or Claude Code connects to the MCP server and starts
making tool calls during a coding session. Midway through
the session, the SSE connection drops. The agent loses
its MCP tools silently. It starts hallucinating answers
instead of querying the knowledge base, because it no longer
has access to the tool. The developer does not notice and
ships code based on hallucinated documentation.

### Root cause
SSE connections are long-lived and stateful. Any network
hiccup, EC2 load spike, or MCP server restart drops every
active connection. Unlike HTTP which is stateless and
reconnects transparently, SSE requires explicit reconnection
logic on the client side.

Also: if we redeploy the MCP server container (Docker
Compose restart), all active SSE connections are killed.
Zero-downtime deploy is not possible with SSE without
careful design.

### Probability: MEDIUM (SSE connection drops are common
in real-world deployments)

### Impact: MEDIUM — agent silently loses capability,
developer gets bad AI assistance without knowing why

### Prevention
MCP server implements SSE reconnection heartbeat:
  Send SSE heartbeat comment every 30 seconds
  Clients (Cursor, Claude Code) detect missed heartbeats
  and attempt reconnection automatically
  MCP SDK handles reconnection — we just need the heartbeat

Graceful restart strategy:
  Never kill MCP server abruptly during deploy
  Send SIGTERM → drain existing connections (30s grace period)
  → start new container → old container exits
  Docker Compose supports this with stop_grace_period: 30s

MCP tool response includes connection health signal:
  Every tool response includes a server_version field
  If client sees version mismatch after reconnect, it
  knows a restart happened and can inform the developer

### Detection
Prometheus metric: mcp_active_connections
Alert: connections drop to 0 during expected active hours
Log: SSE connection drops with duration and tenant_id

---

## FAILURE 8: Celery Job Silently Fails Without Retry

### What happens
An ingestion job starts, processes 400 of 500 documents,
then fails on document 401 (malformed PDF, network timeout
to GitHub API, embedding API error). The job is marked
failed in PostgreSQL. The tenant admin sees a failed job.
They re-trigger it. But because we do not checkpoint
progress, the job starts from document 1 again. The 400
already-processed documents get re-embedded. Cost doubles.
Time doubles. Qdrant gets duplicate chunks.

### Root cause
No job checkpointing. No idempotent chunk writes. Celery
retry restarts the entire job from scratch instead of
resuming from the last successful document.

### Probability: HIGH (network errors to GitHub API and
PDF parsing failures are common)

### Impact: MEDIUM — cost and time waste, potential
duplicate chunks in Qdrant degrading retrieval quality

### Prevention
Idempotent chunk writes to Qdrant:
  Each chunk has a deterministic ID based on:
  sha256(tenant_id + source_url + chunk_index)
  Qdrant upsert (not insert) on every chunk write
  Same chunk written twice = same result, no duplicate

Job-level checkpointing:
  Ingestion job tracks last successfully processed
  document URL in PostgreSQL (checkpoint_url column)
  On retry, Celery worker resumes from checkpoint_url
  not from document 1

Per-document error handling:
  A single malformed PDF does not fail the entire job
  Log the error, increment docs_failed counter, continue
  Only fail the entire job if > 20% of documents fail
  (indicates systematic problem, not one-off error)

Exponential backoff on external API calls:
  GitHub API timeout → retry 3x with backoff before
  marking that document as failed

### Detection
Prometheus metric: celery_task_failure_rate
Alert: failure rate > 5% over 10 minutes
Log: every failed document with tenant_id, source_url,
error_type, retry_count

---

## PRE-MORTEM SUMMARY

Failure | Probability | Impact | Primary Prevention
--------|-------------|--------|-------------------
1. Faithfulness degrades silently | HIGH | CRITICAL | Continuous RAGAS eval + model pinning
2. Bulk upload kills all queries | MEDIUM | HIGH | Docker resource limits + pipeline separation
3. Qdrant RAM exhaustion | MEDIUM | CRITICAL | Proactive RAM monitoring + doc limits per tenant
4. OpenAI outage | HIGH | HIGH | Circuit breaker + chunk fallback response
5. Cross-tenant data leakage | LOW | CATASTROPHIC | DB-layer isolation + automated leak tests in CI
6. Incremental re-index misses deletions | HIGH | MEDIUM | Weekly full re-index + URL fingerprinting
7. MCP connection instability | MEDIUM | MEDIUM | SSE heartbeat + graceful restart
8. Celery job fails without checkpoint | HIGH | MEDIUM | Idempotent writes + job checkpointing

The three that will definitely happen and need to be solved
before any real users are onboarded:

1. Faithfulness degradation — set up RAGAS eval pipeline
   before writing a single line of feature code
4. OpenAI outage — circuit breaker is mandatory day one
6. Ghost content from deletions — weekly full re-index
   must be scheduled before first tenant ingests anything

Everything else is important but can be addressed
progressively as the system matures.










