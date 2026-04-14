# Step 3 — Non-Functional Requirements

NFRs are not just a list of quality attributes. Each one has a
number, a reason, and an architecture implication. 

Format which I follow for every NFR: Metric → Number → Why → Architecture impact

Where relevant, I have documented the current choice (personal
project scale) and the production alternative (if this were a
real B2B SaaS). The Strategy pattern on every component means
switching is a config change not a rewrite.

---

## THE MOST IMPORTANT ARCHITECTURAL DECISION BEFORE ANYTHING ELSE

Indexing pipeline and query pipeline are two completely separate
services. They scale on different axes and mixing them is the
fastest way to kill query performance when ingestion load spikes.

Indexing Pipeline:
- Bottleneck is throughput — how many documents processed per hour
- Workload is CPU heavy, long-running, runs in background
- User is NOT waiting — high latency tolerance (minutes are fine)
- Needs a queue to handle burst uploads and automatic retries
- Scales horizontally by adding more workers

Query Pipeline:
- Bottleneck is concurrent in-flight LLM connections + Qdrant RAM
- Workload is latency-sensitive — user or agent is waiting
- Needs async FastAPI with semaphore-based LLM concurrency limiter
- Does NOT need a queue at v1 scale (1 QPS peak)
- Scales by increasing async concurrency and Qdrant instance RAM

Real consequence of mixing them: one tenant uploads 500 docs,
ingestion workers get saturated, query workers starve, every user
sees latency spikes. Separation means ingestion load never touches
query performance.

---

## P — PERFORMANCE

### Latency (Query Pipeline)

p50 < 500ms
WHY: Developer tools live and die by feel. If querying from Cursor
takes 2+ seconds every time, engineers quietly stop using it.
ARCHITECTURE IMPACT: Redis exact-match cache for repeated queries.
Streaming LLM responses so first token hits user fast. Reranker
must be a lightweight cross-encoder & not another LLM call.

p95 < 2s
WHY: Even complex queries hitting large knowledge bases with
reranking and conversation history injection should finish under 2s.
ARCHITECTURE IMPACT: Strict timeouts on retrieval and reranking.
Top-K hard capped at 20 chunks. Lowest-ranked chunks dropped first
if token budget is exceeded, never truncated mid-chunk.

p99 < 4s
WHY: The 1% edge cases — cold starts, massive PDFs, deep GitHub
repos.
ARCHITECTURE IMPACT: Pre-warmed containers. Connection pooling to
Qdrant and OpenAI. Circuit breaker on every external dependency
so one slow LLM call does not cascade into full system failure.

### Internal Latency Budget Per Query
Embedding generation (text-embedding-3-small): < 100ms
Hybrid retrieval (Qdrant dense + BM25 sparse): < 200ms
Reranking (Cohere cross-encoder): < 200ms
Context building + conversation history injection: < 50ms
LLM generation via streaming (GPT-4o): < 1,500ms
First token to user: < 500ms
Total at p95: ~2s ✅

### Ingestion Throughput (Indexing Pipeline)
500 documents/hour minimum per tenant
WHY: A medium docs site has 200-500 pages. Initial ingestion must
finish in under an hour not overnight. Nobody wants to wait 6 hours
before they can query their knowledge base.
ARCHITECTURE IMPACT: Ingestion runs as async background jobs
completely decoupled from the query path. Queue absorbs burst
uploads. Failed jobs retry automatically with exponential backoff.
If one tenant uploads 500 docs, other tenants see zero impact on
query performance.

---

## A — AVAILABILITY

### Uptime Targets

Personal project (v1): 99.5% (single region, single AZ)
= ~44 hours downtime/year
WHY: At 5 tenants, this is a developer tool not a payment system.
If it goes down for an hour, engineers fall back to manual doc
search — annoying but not catastrophic. Building 99.9% from day
one requires multi-AZ complexity completely unjustified at this
scale.

B2B SaaS (v2 onwards): 99.9% (multi-AZ, same region)
= ~8.7 hours downtime/year
WHY: Once teams depend on MCP tools during active coding sessions
and paying customers have SLA expectations, downtime becomes
genuinely painful. Multi-AZ protects against single instance
failure without the cost of multi-region.

B2B SaaS at scale (v3): 99.99% (multi-region active-passive)
= ~52 minutes downtime/year
WHY: Enterprise customers with global teams need this. Justified
only when enterprise ARR makes the infra cost worthwhile.

ARCHITECTURE IMPACT:
v1 → single EC2 with health checks and auto-restart via systemd
  or ECS
v2 → ALB in front of 2 instances across different AZs
v3 → Route53 failover + multi-region deployment

### Graceful Degradation
System never returns a blank error. Every external dependency has
a defined fallback behavior.

Qdrant down → fall back to BM25 keyword search only, tell user
  semantic search is temporarily unavailable
OpenAI down → return retrieved chunks with no generated answer,
  tell user LLM is unavailable right now
Reranker down → skip reranking, pass raw top-5 retrieval chunks
  directly to LLM
Redis down → bypass cache entirely, query pipeline directly
  (slower but fully functional)
Conversation history DB down → answer without history context,
  log warning, do not fail the request

ARCHITECTURE IMPACT: Circuit breaker on every external call.
Each component fails independently without taking down the others.
This is not optional — it is what separates a production system
from a demo.

---

## S — SCALABILITY

### Two Separate Things: Data Model Design vs Infrastructure Sizing

Data models, partition strategy, and API contracts must be
designed for 100 tenants from day one. These are painful or
impossible to change later without migrations across millions
of rows.

Infrastructure sizing (instances, RAM, worker counts) starts
small for 5 tenants and scales up as needed. Easy to change.

What "designed for 100 tenants from day one" means concretely:

tenant_id in every PostgreSQL table from day one
  → Adding this later = migration across millions of rows

One Qdrant collection per tenant from day one
  → Starting with a shared collection and splitting later means
    rebuilding the entire vector index from scratch

API key scoped to tenant_id server-side from day one
  → Changing auth model later breaks every client integration
    that any tenant has already built

S3 paths as tenant-{id}/docs/ from day one
  → Reorganizing S3 at scale is an operational nightmare

### User Scale
Launch: 5 tenants, ~100 queries/day
6 months: 30 tenants, ~2,000 queries/day
1 year: 100 tenants, ~10,000 queries/day

### QPS Estimate (Query Pipeline)
At 10,000 queries/day:
Average QPS = 10,000 / 86,400 = 0.12 QPS
Peak QPS (80% in 8 business hours) = ~0.28 QPS
Design target with 3x safety margin = ~1 QPS

This is very low QPS. The bottleneck here is NOT how many
requests arrive per second. It is how many LLM calls are
concurrently in-flight and how much RAM Qdrant needs to hold
all tenant embeddings in memory at once.

What this means in practice:
- Use async FastAPI not sync Flask — threads sit idle waiting
  on OpenAI network calls, not doing CPU work. Sync = wasted
  threads.
- Size Qdrant instance by RAM not CPU cores
- Set semaphore on LLM concurrency (max 20 concurrent calls)
  not a request queue — queue adds latency with no benefit here
- Monitor concurrent open OpenAI connections not just QPS

### Message Queue Decision (Current vs Production)

Current choice — Personal project: Celery + Redis
WHY: Redis is already in the stack for caching and rate limiting.
Celery on top of existing Redis costs nothing extra. Simple to
set up, easy to debug locally. At 5-30 tenants triggering
occasional ingestion jobs, this is more than enough.
DOWNSIDE: If EC2 goes down, Redis goes down with it — in-flight
jobs could be lost.

Production alternative — B2B SaaS: SQS + workers (ECS or Lambda)
WHY: SQS is fully managed, never goes down, messages persist
even if entire EC2 fleet crashes. Built-in dead letter queue
for failed jobs. Serverless Lambda workers scale to zero when
idle (cost efficient). This is the right choice when guaranteed
message persistence and serverless scaling matter.
SWITCH TRIGGER: When guaranteed job persistence across
infrastructure failure becomes a hard business requirement
(paying customers, SLA commitments).

Queue Strategy Pattern — same interface, swap implementation:
  QueueStrategy (interface)
    → enqueue(job) → job_id
    → dequeue() → job
    → ack(job_id)

  CeleryRedisQueue implements QueueStrategy (current)
  SQSQueue implements QueueStrategy (production)

Switching is a one-line config change. Zero pipeline logic
changes needed.

Where queue is used and where it is not:

Indexing pipeline — queue is MANDATORY from day one
WHY: Ingestion is long-running (minutes not milliseconds).
Multiple tenants can trigger ingestion simultaneously. Burst
uploads (one tenant uploads 500 docs) must not impact any other
tenant. Failed jobs need automatic retry from last checkpoint
without human intervention.

Query pipeline — no queue needed at v1 scale
WHY: At 1 QPS peak, async FastAPI with a semaphore handles this
comfortably. A queue in the query path adds latency with zero
benefit at this scale.
REVISIT TRIGGER: If peak query QPS exceeds 20 sustained, add
a priority query queue (paying tenants served before free ones).

### Vector DB Memory Sizing (Qdrant)
Per chunk:
  1536 dimensions × 4 bytes = 6KB for embedding vector
  ~500 bytes for metadata
  ~6.5KB total per chunk

Per tenant (5,000 docs × 10 chunks avg):
  50,000 chunks × 6.5KB = ~325MB per tenant

At 100 tenants:
  100 × 325MB = ~32GB total

ARCHITECTURE IMPACT: Qdrant on a single r6g.xlarge (32GB RAM)
handles full 1-year scale comfortably. No sharding needed until
500+ tenants. Start vertical (bigger instance), shard horizontal
only when forced.

---

## S — SECURITY

### Authentication

Personal project: API key per tenant
WHY: Simple, easy to rotate, easy to scope. Perfect for
machine-to-machine use cases like AI agents calling MCP tools.

B2B SaaS addition: OAuth 2.0 + SSO (SAML) for enterprise
WHY: Enterprise customers require SSO integration with their
existing identity providers (Okta, Azure AD). API keys remain
for machine-to-machine but human users authenticate via SSO.

ARCHITECTURE IMPACT: tenant_id is always derived from API key
server-side — never trusted from request body. Even if
application code has a bug, a tenant cannot query another
tenant's namespace.

### Data Isolation
This is the most critical security property in any multi-tenant
system. One data leakage incident destroys trust permanently.

Qdrant: one collection per tenant (isolated at DB layer)
PostgreSQL: tenant_id on every row + Row Level Security (RLS)
S3: tenant-prefixed paths → s3://bucket/tenant-{id}/docs/
Redis: tenant-prefixed cache keys → cache:{tenant_id}:{hash}

Isolation enforced at the database layer not just the application
layer. Application bugs cannot cause cross-tenant data leaks.

### Encryption
In transit: TLS 1.3 for all API and MCP communication
At rest: AES-256 for all stored documents and embeddings

B2B SaaS addition: field-level encryption for any PII in
documents, customer-managed encryption keys (CMEK) for
enterprise tier.

### Rate Limiting
Personal project: 60 req/min per tenant (Redis sliding window)
B2B SaaS: tiered limits per plan (free / pro / enterprise)
  Free: 20 req/min
  Pro: 100 req/min
  Enterprise: configurable

ARCHITECTURE IMPACT: Redis sliding window counter.
Key pattern: ratelimit:{tenant_id}:{minute}

---

## R — RELIABILITY

### Data Durability
Raw documents (S3): 99.999% — source of truth, never lose this
Embeddings (Qdrant): 99.9% — derived data, rebuildable from S3
Conversation history (PostgreSQL): 99.9% — continuous backup
Query logs: 99.9% — important for debugging, not critical

Key insight: embeddings are derived data. If Qdrant is lost,
re-run ingestion from S3 and rebuild. S3 is the real source of
truth. Qdrant is the queryable index on top of it.

### RPO and RTO
Raw documents: RPO = 0 (S3 versioning + sync replication)
Embeddings: RPO = 24 hours (rebuilt from last full re-index)
Conversation history: RPO = 1 hour (PostgreSQL continuous backup)
Full system RTO: < 30 minutes (restore Qdrant snapshot + restart)

B2B SaaS RPO targets:
  Critical data (auth, billing): RPO = 0
  Embeddings: RPO = 4 hours (more frequent re-index jobs)
  Full system RTO: < 5 minutes (auto-failover, multi-AZ)

### Circuit Breaker Config
OpenAI API: Opens after 5 failures in 60s → open for 60s →
  half-open → fallback: return chunks without LLM generation
Qdrant: Opens after 3 failures in 30s → fallback: BM25 only
Reranker: Opens after 3 failures in 30s → fallback: raw top-5

---

## C — COST

### Cost Targets
Personal project per query: < $0.02
Personal project per tenant/month (2,000 queries): < $40
Personal project infrastructure at 1-year scale: < $500/month

B2B SaaS target (to be profitable):
  Cost per query: < $0.01 (with caching and model routing)
  Gross margin target: > 60% (standard SaaS benchmark)

### Cost Per Query Breakdown
text-embedding-3-small (OpenAI): ~$0.00002
Cohere rerank-english-v3: ~$0.002
GPT-4o (OpenAI): ~$0.015
Qdrant compute (self-hosted, amortized): ~$0.001
Total per query: ~$0.018 ✅

### Primary Cost Drivers (ranked)
1. LLM API calls (GPT-4o): ~80% of per-query cost
2. Reranker (Cohere): ~12%
3. Embedding generation: ~5%
4. Infrastructure (EC2 + Qdrant): ~3%

### Cost Optimization Strategy

Exact-match Redis cache (TTL: 1 hour):
  Repeated identical queries skip OpenAI call entirely.
  Target 30% cache hit rate at steady state.
  Saves ~$0.015 per cached query.

  B2B SaaS upgrade: semantic caching (embedding similarity >
  0.95 threshold). Target 60-70% cache hit rate. This alone
  cuts LLM cost by more than half at scale.

Model routing via Strategy pattern:
  Personal project: GPT-4o-mini for simple, GPT-4o for complex
  B2B SaaS: add Claude Sonnet as fallback + cost-based routing
  Estimated 40% of queries are simple → saves ~35% LLM cost

Context window optimization:
  Send top-5 chunks + last 3 conversation turns only.
  Hard cap: 6,000 input tokens (checked via tiktoken).
  Lowest-ranked chunks dropped first if over budget.
  Never truncate mid-chunk as it destroys context quality.

Qdrant self-hosted vs Pinecone managed:
  Personal project: self-hosted saves $70-200/month
  B2B SaaS: evaluate managed Qdrant Cloud when ops burden
  of self-hosting exceeds cost of managed service
  Strategy pattern makes this a one-line config change either way

---

## C — CONSISTENCY

### Strong Consistency (CP) — PostgreSQL
Tenant API key → namespace mapping
WHY: Wrong mapping = queries go to wrong namespace = data
leakage incident. Must always be correct. No exceptions.

Rate limiting counters (Redis atomic INCR)
WHY: Must be atomic. Eventual consistency here means tenants
exceed quota within the same window.

### Eventual Consistency (AP) — acceptable here
Vector index freshness: 24-hour staleness is fine
Conversation history reads: 1-second staleness is fine
Evaluation metrics: batch computed, no real-time requirement

---

## LLM-SPECIFIC NFRs

### Strategy Pattern — Every Component Is Swappable

Every LLM-adjacent component sits behind a Strategy interface.
Swapping providers is a config change not a code change.

EmbeddingStrategy:
  Default → text-embedding-3-small (OpenAI)
  Alternatives → Cohere embed-english-v3, Amazon Titan v2

LLMStrategy:
  Default → GPT-4o (OpenAI)
  Routing → GPT-4o-mini for simple, GPT-4o for complex queries
  Future → Claude 3.5 Sonnet, Gemini 1.5 Pro

VectorDBStrategy:
  Default → Qdrant (self-hosted, zero extra cost)
  Production alternative → Qdrant Cloud or Pinecone managed

RerankerStrategy:
  Default → Cohere rerank-english-v3
  Alternative → BGE reranker (local, free, zero API cost)

QueueStrategy:
  Default → Celery + Redis (already in stack)
  Production alternative → SQS + ECS/Lambda workers

WHY THIS MATTERS: OpenAI changes pricing. Models get deprecated.
Providers have outages. A system hardcoded to one provider is a
liability. This pattern is what makes the codebase maintainable
for years not months.

### Model Versioning
Pin to specific versions in production always:
  GPT-4o → pinned via OpenAI API version header
  text-embedding-3-small → pinned via OpenAI API version
  rerank-english-v3 → Cohere pinned version

WHY: Providers update models silently. Unpinned models mean
random behavior changes in production with zero warning. This
is how faithfulness scores silently degrade and nobody knows
why until a tenant complains.

### Response Quality SLOs
Faithfulness ≥ 0.90 (RAGAS, measured on golden dataset)
Answer relevance ≥ 0.85
Context precision ≥ 0.80
Hallucination rate < 5%
"I don't know" rate: tracked, no hard target (honesty > coverage)

These are the same targets which I achieved at Softeon (0.67 → 0.91
faithfulness jump). Achievable with hybrid retrieval + reranking
+ strict grounding prompt.

### Token Budget Per Query
System prompt: ~500 tokens (fixed, cached, version-controlled)
Top-5 retrieved chunks: ~4,000 tokens (800 avg per chunk)
Last 3 conversation turns: ~600 tokens
Current query + rewritten query: ~500 tokens
Total input hard cap: 6,000 tokens
Output hard cap: 1,000 tokens

Token count checked via tiktoken before every LLM call.
If over budget, lowest-ranked chunks dropped first.
Never truncated mid-chunk.

### Conversation History (v1 — PostgreSQL)
Last 3 turns stored in PostgreSQL per session_id
session_id passed with every API and MCP query
Last 3 turns injected into context window before LLM call
Session expires after 1 hour of inactivity
No vector-based semantic memory in v1 — that is v2

Database choice: PostgreSQL not DynamoDB
WHY: Access pattern is simple key lookup by session_id. AP
consistency is fine — 1 second staleness does not matter here.
At our scale (10,000 queries/day), PostgreSQL handles this with
zero strain. We are already running it for tenant and API key
management. DynamoDB adds cost and operational complexity with
zero benefit until we hit 1M+ queries/day.

B2B SaaS upgrade path: if conversation history becomes a high
write-throughput bottleneck (millions of queries/day), migrate
to DynamoDB. Repository pattern on the data access layer makes
this migration a config change not a rewrite.

### Prompt Regression Testing
Golden dataset: 100+ query-answer pairs per tenant
Evaluation runs on every prompt change before deployment
Deployment blocked if faithfulness drops below 0.85
New prompts shadow-tested on 10% traffic before full rollout

### LLM Observability Per Query
Every single query logs:
  Input tokens, output tokens, model version used, TTFT,
  total latency breakdown (retrieval / reranking / LLM),
  cost in dollars, cache hit or miss, reranker scores,
  faithfulness score (async post-response), tenant ID,
  session ID, query rewrite applied or not

Tools: LangSmith for full trace, Prometheus for metrics,
Grafana for dashboards.

B2B SaaS addition: per-tenant cost dashboard so customers
can see their own usage and costs in real time. This is
table stakes for any B2B developer tool charging per query.