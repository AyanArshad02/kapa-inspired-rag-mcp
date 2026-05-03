# Step 7 — Architectural Decision Records (ADRs)

An ADR is not a list of tools we picked. It is a record of
WHY we picked them, what we rejected and why, and exactly
when we should revisit the decision.

Every ADR follows this format:
  Context → Decision → Alternatives Rejected → Consequences
  → Revisit Trigger

---

## ADR-001: Separate Indexing and Query Pipelines

Date: 2026
Status: ACCEPTED

### Context
The system has two fundamentally different workloads. Ingestion
is throughput-bound — it processes large batches of documents
in the background and can tolerate high latency. Querying is
latency-bound — a user or AI agent is waiting for a response
and expects sub-2 second answers.

If both pipelines share the same process, a burst ingestion
job (one tenant uploading 500 docs) saturates the worker pool
and query latency spikes for every other tenant. This is not
a theoretical risk — it is exactly what happens in every
monolithic RAG implementation that skips this separation.

### Decision
Run indexing and query pipelines as completely separate
processes with clearly defined boundaries. They share the
storage layer (Qdrant, PostgreSQL, S3, Redis) but nothing
else.

Indexing pipeline:
  FastAPI ingestion service (:8001) → receives job, enqueues
  Celery workers → does the actual heavy lifting
  Celery Beat → schedules incremental and full re-index jobs
  Scales by: adding more Celery worker processes

Query pipeline:
  FastAPI query service (:8000) → handles all query traffic
  Async throughout — semaphore on LLM concurrency
  Scales by: increasing async concurrency, Qdrant RAM

### Alternatives Rejected

Single FastAPI service handling both:
  Rejected because ingestion CPU load directly impacts query
  latency. One tenant's bulk upload degrades every other
  tenant's query experience. Unacceptable for a multi-tenant
  system.

Separate microservices from day one (different repos, k8s):
  Rejected because at 5-30 tenants, this adds k8s operational
  complexity with zero benefit. Docker Compose on a single EC2
  with separate processes achieves the same isolation at a
  fraction of the operational cost.

### Consequences
Positive:
  Ingestion load never touches query latency
  Each pipeline scales independently
  Clear code boundaries — easier to test and debug

Negative:
  Two FastAPI services to deploy and monitor instead of one
  Slightly more complex Docker Compose setup

### Revisit Trigger
If ingestion and query services need to scale to completely
different instance types (GPU for embedding vs CPU for query),
split them onto separate EC2 instances at that point.

---

## ADR-002: Qdrant for Vector Storage (Self-Hosted)

Date: 2026
Status: ACCEPTED

### Context
We need a vector database that supports hybrid search (dense
semantic + sparse keyword) natively, provides strong tenant
isolation, and fits within a personal project budget.

The hybrid search requirement is non-negotiable. Every query
runs hybrid retrieval — this is what gets us from 0.67 to
0.91 faithfulness. A DB that forces us to stitch hybrid search
together ourselves adds latency, code complexity, and failure
points.

### Decision
Self-hosted Qdrant running in Docker, co-located with other
services on the same EC2 during v1. One Qdrant collection per
tenant for hard namespace isolation.

Why Qdrant specifically:
  Native hybrid search — dense and sparse retrieved in parallel
  in a single API call. RRF fusion is built in. No custom
  merge code.
  HNSW index for dense (approximate nearest neighbor)
  Native sparse vector support (SPLADE format)
  Collection-per-tenant gives DB-layer isolation, not just
  application-layer isolation
  Self-hosted = zero extra cost at our scale
  Runs in Docker — identical setup locally and on EC2

### Alternatives Rejected

Pinecone (managed):
  Rejected for two reasons.
  First: hybrid search requires two separate API calls (dense
  and sparse) and custom RRF merge code. That is extra latency
  and extra code we do not want to maintain.
  Second: $70-200/month minimum cost. Free tier is limited to
  2GB storage and pauses indexes after 3 weeks of inactivity
  — unusable for a system with scheduled re-index jobs.
  NOTE: We use Pinecone free tier during initial development
  only (first 2-3 weeks) to validate the pipeline without
  infrastructure setup. Switch to self-hosted Qdrant before
  onboarding any real tenants.

Elasticsearch / OpenSearch for BM25:
  Rejected because it means running a second service just for
  keyword search. Qdrant's native sparse vector support handles
  BM25-equivalent retrieval without a separate Elasticsearch
  cluster. One less service, one less failure point.

Weaviate:
  Rejected because Qdrant's hybrid search implementation is
  more mature and the collection-per-tenant isolation model
  is cleaner for our multi-tenant use case.

pgvector (PostgreSQL extension):
  Rejected because we are already using PostgreSQL for
  relational data. Mixing vector search and relational queries
  in the same DB creates resource contention. PostgreSQL is
  not optimized for high-dimensional vector search at scale.
  Also lacks native sparse vector support.

### Consequences
Positive:
  Hybrid search in one API call with ~200ms latency
  Zero extra cost at personal project scale
  Hard tenant isolation at DB layer
  Local dev identical to production

Negative:
  We manage Qdrant ourselves — upgrades, snapshots, restarts
  If EC2 goes down, Qdrant goes with it (mitigated by
  Qdrant snapshots + S3 as source of truth for rebuilding)

### Revisit Trigger
If self-hosting operational burden becomes too high (team
grows, multiple engineers needed), evaluate Qdrant Cloud
(managed Qdrant — same API, zero ops). VectorDBStrategy
pattern makes this a one-line config change.

---

## ADR-003: Strategy Pattern on Every Swappable Component

Date: 2026
Status: ACCEPTED

### Context
This system depends on multiple external AI providers —
OpenAI for embeddings and generation, Cohere for reranking,
Qdrant for vector search. AI providers change pricing, deprecate
models, have outages, and release better alternatives
constantly.

A system hardcoded to one provider is one deprecation notice
away from an emergency rewrite. We have seen this happen to
production systems. It is not theoretical.

### Decision
Every provider-dependent component sits behind a Strategy
interface. The concrete implementation is injected via config.
Swapping providers requires changing one environment variable,
not touching pipeline logic.

Interfaces defined:

LLMStrategy:
  generate(messages, stream) → response
  Implementations: OpenAILLM, ClaudeLLM, GeminiLLM
  Default: OpenAILLM (GPT-4o)
  Model routing: GPT-4o-mini for simple, GPT-4o for complex

EmbeddingStrategy:
  embed(texts) → vectors
  Implementations: OpenAIEmbedding, CohereEmbedding
  Default: OpenAIEmbedding (text-embedding-3-small)

VectorDBStrategy:
  upsert(chunks), search(query_vector) → chunks
  Implementations: QdrantDB, PineconeDB
  Default: QdrantDB

RerankerStrategy:
  rerank(query, chunks) → ranked_chunks
  Implementations: CohereReranker, BGEReranker
  Default: CohereReranker (rerank-english-v3)

QueueStrategy:
  enqueue(job), dequeue() → job, ack(job_id)
  Implementations: CeleryRedisQueue, SQSQueue
  Default: CeleryRedisQueue

ConnectorStrategy (Factory pattern):
  fetch(source) → raw_documents
  Implementations: DocsConnector, GitHubConnector,
                   PDFConnector, SlackConnector
  Adding new connector: implement interface, register in
  factory, zero pipeline changes

### Alternatives Rejected

Hardcoded provider calls throughout the codebase:
  Rejected because this is how RAG systems accumulate
  technical debt. Every provider switch becomes a grep-and-
  replace exercise across dozens of files. We have seen this
  firsthand.

LangChain abstractions:
  Considered. Rejected because LangChain's abstractions are
  leaky — they expose provider-specific quirks through the
  abstraction layer, and the framework itself changes rapidly.
  Writing thin Strategy interfaces ourselves gives us full
  control with the same benefit. Less magic, more predictable.

### Consequences
Positive:
  Provider switch = one config line change
  Each implementation is independently testable with mocks
  New providers can be added without touching pipeline logic
  Clear separation between business logic and provider details

Negative:
  More upfront interface design
  Slightly more boilerplate code per implementation
  Engineers must remember to go through the interface,
  not call providers directly

### Revisit Trigger
Never revisit the pattern itself. Revisit specific
implementations when provider pricing or quality changes.

---

## ADR-004: PostgreSQL for All Relational Data

Date: 2026
Status: ACCEPTED

### Context
The system needs to store tenant metadata, API keys, ingestion
job status, conversation history, and session data. Each of
these has different consistency requirements but they are all
relational, low-to-medium volume, and involve occasional
joins or transactions.

### Decision
Single PostgreSQL RDS instance for all relational data.
Row Level Security (RLS) enforced on every table.
tenant_id column on every table from day one.

Tables on PostgreSQL:
  tenants, api_keys (CP — auth critical)
  ingestion_jobs (CP — status transitions need ACID)
  sessions, conversation_turns (AP acceptable but PostgreSQL
  is more than sufficient at our scale)

### Alternatives Rejected

DynamoDB for conversation history:
  The textbook choice for append-only, key-lookup data.
  Rejected at our scale because:
  At 10,000 queries/day, conversation_turns write throughput
  is 0.12 writes/sec. PostgreSQL handles 1,000+ writes/sec.
  We are already running PostgreSQL. DynamoDB adds $50-100/month
  and another AWS service to debug for zero performance benefit.
  REVISIT: If writes exceed 500/sec (happens at ~250M queries/day)
  migrate conversation_turns to DynamoDB. Repository pattern
  makes this a config change not a rewrite.

MongoDB for flexible schema:
  Rejected because our schema is well-defined and stable.
  MongoDB's flexible schema is a benefit for rapid iteration
  on unknown data shapes. We know our data shapes. PostgreSQL
  with JSONB handles any semi-structured fields we need.

Separate PostgreSQL instances per concern:
  Rejected at our scale. One RDS instance handles all tables
  comfortably. Splitting adds connection management complexity
  and costs with no benefit until we hit 10M+ queries/day.

### Consequences
Positive:
  ACID transactions across tenant + api_key creation
  RLS enforced at DB layer — application bugs cannot leak
  cross-tenant data
  One service to operate, monitor, and back up
  Familiar, well-understood tooling

Negative:
  Single point of failure until we add Multi-AZ (v2)
  Vertical scaling ceiling (mitigated by read replicas later)

### Revisit Trigger
Add RDS Multi-AZ when availability requirement moves to 99.9%.
Add read replica when query service read throughput exceeds
500 reads/sec on the PostgreSQL tables.

---

## ADR-005: Redis for Cache, Rate Limiting, and Job Queue

Date: 2026
Status: ACCEPTED

### Context
Three separate concerns need a fast in-memory store:
exact-match response caching, per-tenant rate limiting with
atomic counters, and the Celery job queue for ingestion jobs.

### Decision
Single Redis instance handles all three. Each concern uses
a distinct key namespace to avoid collisions.

Cache:        cache:{tenant_id}:{sha256(query)}  TTL: 3600s
Rate limit:   ratelimit:{tenant_id}:{minute}      TTL: 60s
Celery queue: managed by Celery internally

### Alternatives Rejected

Separate Redis instances per concern:
  Rejected. At our scale, a single Redis instance with 1GB RAM
  handles all three concerns with headroom to spare. Splitting
  adds operational complexity with zero performance benefit
  at our QPS.

Memcached for cache:
  Rejected because Redis supports TTL natively, has atomic
  INCR for rate limiting, and serves as the Celery broker.
  Three features in one service. Memcached gives us only
  the cache.

SQS for job queue instead of Redis:
  SQS is the correct production choice — fully managed,
  guaranteed message persistence, built-in dead letter queue.
  Rejected at personal project scale because Redis is already
  in the stack. Adding SQS adds cost ($0.40/1M messages) and
  another AWS service to configure.
  REVISIT: When guaranteed job persistence across EC2 failure
  becomes a hard requirement (paying customers, SLA). QueueStrategy
  pattern makes switching a one-line config change.

### Consequences
Positive:
  One service, three responsibilities
  Sub-millisecond reads for cache and rate limiting
  Atomic INCR prevents rate limit race conditions
  Zero extra cost

Negative:
  If EC2 goes down, Redis goes with it — in-flight cache
  and pending queue jobs are lost
  Mitigated by: cache is disposable (rebuild on miss),
  queue loss is mitigated by job status in PostgreSQL
  (admin can re-trigger failed jobs)

### Revisit Trigger
Move to ElastiCache (managed Redis) when Redis availability
becomes a hard requirement. Move Celery queue to SQS when
guaranteed job persistence across infrastructure failure
is required.

---

## ADR-006: Celery + Redis for Ingestion Job Queue

Date: 2026
Status: ACCEPTED

### Context
Ingestion jobs are long-running (minutes not milliseconds),
triggered by multiple tenants simultaneously, and must retry
automatically on failure. This is a classic async job queue
problem.

### Decision
Celery with Redis as the broker. Three worker processes at
launch. Celery Beat for scheduled re-index jobs.

Why Celery:
  Redis is already in the stack — zero extra broker cost
  Celery handles retries, exponential backoff, dead letter
  queues natively
  Worker count is just a config number — easy to scale
  Celery Beat handles scheduled tasks (daily incremental,
  weekly full re-index) without a separate cron system
  Local dev identical to production — same Docker Compose

### Alternatives Rejected

SQS + Lambda workers:
  The correct choice for a production B2B SaaS:
  Fully managed, infinite scale, serverless (scales to zero
  when idle), guaranteed message persistence across EC2 failure,
  built-in dead letter queue.
  Rejected at personal project scale because Redis is already
  in the stack and Celery on top of it costs nothing extra.
  At 43 ingestion jobs/day, Lambda cold starts and SQS
  configuration complexity are not justified.
  REVISIT: When paying customers require SLA guarantees on
  ingestion jobs or when Celery worker management becomes
  an operational burden.

Celery + RabbitMQ:
  RabbitMQ is a more feature-rich message broker than Redis.
  Rejected because Redis handles our queue requirements
  adequately and we are already running it. One less service.

### Consequences
Positive:
  Zero extra cost (Redis already in stack)
  Simple setup — works identically locally and on EC2
  Retry logic, backoff, and scheduling built in

Negative:
  Redis going down takes the queue with it
  Not serverless — workers are always running even when idle
  (acceptable cost at our scale)

### Revisit Trigger
Move to SQS when guaranteed job persistence across
infrastructure failure becomes a hard business requirement.

---

## ADR-007: EC2 + Docker Compose over ECS Fargate (v1)

Date: 2026
Status: ACCEPTED

### Context
We need to decide where to run the query service, ingestion
service, MCP server, Celery workers, Redis, and Qdrant.

The key constraint is Qdrant. Qdrant is stateful — it needs
persistent disk storage for its vector indexes. On Fargate,
stateful workloads require EFS (Elastic File System) which
adds latency on every vector read (network-attached storage
vs local NVMe SSD) and costs $0.30/GB/month on top of
Fargate compute.

### Decision
Single EC2 t3.xlarge running everything via Docker Compose
for v1. PostgreSQL on RDS (managed separately). S3 for
raw documents.

Why EC2 over Fargate:
  Qdrant needs local NVMe SSD — Fargate + EFS adds latency
  and cost for no benefit
  Docker Compose on EC2 is simpler to operate and debug than
  ECS task definitions
  Local dev uses the same Docker Compose — no environment
  drift between local and production
  At 5-30 tenants and 1 QPS peak, one EC2 is more than
  enough compute

### Alternatives Rejected

ECS Fargate for all services:
  Rejected because Qdrant + Fargate + EFS is an anti-pattern.
  EFS adds network I/O latency to every vector search call.
  That directly hits our p95 latency target. Not worth it
  at v1 scale.

Kubernetes (EKS):
  Rejected completely at this scale. k8s operational overhead
  for 5 tenants and 1 QPS is engineering theatre. We will
  evaluate k8s if we hit 1,000 tenants and need orchestration
  across a fleet of EC2 instances.

Separate EC2 instances for each service from day one:
  Rejected. At launch scale, everything fits comfortably on
  one t3.xlarge. Separate instances add cost and network
  complexity with zero benefit. We split services onto
  separate instances only when resource contention is
  measured, not predicted.

### Production path (B2B SaaS):
  Qdrant → always stays on EC2 (dedicated r6g.xlarge)
    because it is stateful and memory-bound
  Query service → ECS Fargate (stateless, auto-scales on QPS)
  Ingestion service → ECS Fargate (stateless, lightweight)
  Celery workers → ECS Fargate (auto-scales on queue depth)
  Redis → ElastiCache (managed)
  PostgreSQL → RDS Multi-AZ

### Consequences
Positive:
  Simple operations — SSH in, docker compose logs, done
  Zero EFS latency on Qdrant reads
  Local dev = production, no surprises on deploy
  ~$170/month total infra at launch

Negative:
  Single EC2 is a single point of failure
  Manual scaling (no auto-scaling on EC2 without ASG setup)
  Mitigated by: ECS health checks + auto-restart, 99.5%
  uptime target is achievable with single EC2 + monitoring

### Revisit Trigger
When any of these happens:
  Celery workers consuming enough CPU to impact query latency
  → move workers to separate EC2
  Qdrant RAM approaching instance limit (>80% of 16GB)
  → upgrade to r6g.large or r6g.xlarge
  Need auto-scaling for query service
  → move query service to ECS Fargate

---

## ADR-008: MCP Server as Separate Process

Date: 2026
Status: ACCEPTED

### Context
The MCP server needs to expose tools to AI coding agents
(Cursor, Claude Code, VS Code). MCP uses SSE (Server-Sent
Events) or stdio as its transport protocol — completely
different from the HTTP/REST that the query service speaks.

The question is whether MCP logic lives inside the query
service or in its own process.

### Decision
MCP server runs as a separate process (:8002). It is a thin
protocol translation layer — it receives MCP tool calls,
translates them to internal HTTP requests to the query service
(:8000), and returns MCP-formatted responses. Zero RAG logic
lives in the MCP server.

Why separate process:
  MCP uses SSE/stdio — a different protocol with different
  connection lifecycle from HTTP requests
  MCP connections are long-lived (agent keeps connection open
  during entire coding session). HTTP requests are short-lived.
  Mixing these in one process complicates connection management
  If query service crashes, MCP server can return a clean
  "tool unavailable" error without the whole system going down
  If MCP server crashes, REST API users are completely
  unaffected — zero shared failure mode

### Alternatives Rejected

MCP logic inside query service:
  Rejected because one process managing two protocols (HTTP
  + SSE) with different connection lifecycles is harder to
  reason about, test, and debug. Also means one failure mode
  takes down both interfaces simultaneously.

MCP as a separate repo / completely independent service:
  Rejected because MCP needs to call the query pipeline.
  A separate repo with its own RAG logic means duplicated
  code that drifts apart over time. Thin wrapper calling
  internal HTTP is simpler and keeps a single source of truth
  for RAG logic.

### Consequences
Positive:
  Independent failure modes — MCP and REST API do not take
  each other down
  Clean separation of protocol handling from business logic
  Easy to test MCP layer independently by mocking the query
  service

Negative:
  One more process to manage in Docker Compose
  One internal HTTP hop between MCP server and query service
  (~5ms overhead — completely acceptable)

### Revisit Trigger
Never. This separation is correct at every scale.

---

## ADR-009: OpenAI as Default LLM Provider (GPT-4o)

Date: 2026
Status: ACCEPTED

### Context
We need an LLM for answer generation and a model routing
strategy for cost optimization. The LLMStrategy pattern means
this decision is easily reversible.

### Decision
Default to GPT-4o for complex queries, GPT-4o-mini for simple
factual lookups. Both pinned to specific API versions.

Model routing logic (within OpenAI first):
  Simple query (short, factual, single-hop retrieval) →
    GPT-4o-mini ($0.60/1M output tokens)
  Complex query (multi-hop, reasoning, synthesis) →
    GPT-4o ($15/1M output tokens)
  Estimated 40% of queries are simple →
    saves ~35% on LLM cost

LLMStrategy means switching to Claude 3.5 Sonnet as default is one config line.

### Alternatives Rejected

Self-hosted Ollama / open source LLM:
  Rejected for generation. At our quality targets (faithfulness
  ≥ 0.90), open source models do not match GPT-4o on complex
  technical documentation Q&A without significant fine-tuning.
  Open source embedding models (for FastSPLADE) are fine
  because embedding quality is more consistent across models.

### Consequences
Positive:
  Best-in-class quality for technical documentation Q&A
  Model routing cuts LLM cost by ~35%
  LLMStrategy means switching providers is zero-code

Negative:
  Vendor dependency on OpenAI
  Cost scales with query volume (mitigated by caching and
  model routing)
  OpenAI outages impact system availability (mitigated by
  circuit breaker + fallback to returning raw chunks)

### Revisit Trigger
If faithfulness score on golden dataset drops below 0.85
after any OpenAI model update. If Claude Sonnet consistently
outperforms GPT-4o on our evaluation set. If OpenAI pricing
increases significantly.

---

## ADR SUMMARY TABLE

ADR | Decision | Status | Revisit Trigger
----|----------|--------|-----------------
001 | Separate indexing + query pipelines | ACCEPTED | Resource contention measured
002 | Qdrant self-hosted | ACCEPTED | Ops burden too high → Qdrant Cloud
003 | Strategy pattern on all components | ACCEPTED | Never (always correct)
004 | PostgreSQL for all relational data | ACCEPTED | Conv history > 500 writes/sec
005 | Redis for cache + rate limit + queue | ACCEPTED | Availability SLA tightens
006 | Celery + Redis for ingestion queue | ACCEPTED | SLA on ingestion jobs required
007 | EC2 + Docker Compose over Fargate | ACCEPTED | Resource contention measured
008 | MCP as separate process | ACCEPTED | Never (always correct)
009 | OpenAI GPT-4o as default LLM | ACCEPTED | Faithfulness drops below 0.85











