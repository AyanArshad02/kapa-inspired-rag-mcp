# Step 4 — Capacity Planning

Capacity planning answers three questions:
1. How much load is the system handling?
2. What breaks first under that load?
3. What infrastructure do we need to handle it comfortably?

All numbers flow from DAU and usage assumptions. Every estimate
has a reasoning trail so it can be challenged and updated as
real data comes in.

---

## GIVEN ASSUMPTIONS

These are the inputs everything else is derived from.

Users:
  Launch:   5 tenants,   ~20 active users/tenant = 100 total users
  6 months: 30 tenants,  ~20 active users/tenant = 600 total users
  1 year:   100 tenants, ~20 active users/tenant = 2,000 total users

Usage pattern per user:
  Queries per user per day: ~5 (developer tool, not social media)
  Peak hours: 9am - 5pm local time (80% of traffic in 8 hours)
  Off-peak: remaining 20% spread across 16 hours
  Read/Write ratio for queries: 100% read (query is always a read)
  Ingestion jobs per tenant per week: ~3 (new docs, updates)

Document assumptions per tenant:
  Average documents: 5,000
  Average chunks per document: 10
  Average tokens per chunk: ~500 tokens (800 for large docs)
  Average chunk size on disk: ~6.5KB (6KB vector + 0.5KB metadata)

---

## SCALE ESTIMATION

### Daily Active Users and Queries

Launch (5 tenants):
  Total users: 100
  Queries/day: 100 users × 5 queries = 500 queries/day
  Ingestion jobs/day: 5 tenants × 3/week = ~2 jobs/day

6 months (30 tenants):
  Total users: 600
  Queries/day: 600 × 5 = 3,000 queries/day
  Ingestion jobs/day: 30 × 3/week = ~13 jobs/day

1 year (100 tenants):
  Total users: 2,000
  Queries/day: 2,000 × 5 = 10,000 queries/day
  Ingestion jobs/day: 100 × 3/week = ~43 jobs/day

---

## QPS CALCULATION (QUERY PIPELINE)

Using 1-year numbers as the design target:
  Total queries/day: 10,000

Average QPS:
  10,000 / 86,400 = 0.12 QPS

Peak QPS (80% of traffic in 8 business hours):
  (10,000 × 0.8) / (8 × 3,600) = 8,000 / 28,800 = 0.28 QPS

Design target (3x safety margin):
  0.28 × 3 = ~1 QPS

This is very low QPS. The bottleneck is NOT requests per second.
It is concurrent in-flight LLM connections and Qdrant RAM.

Concurrent LLM connections at peak:
  Formula: Concurrent = QPS × avg LLM latency
  = 1 QPS × 2s avg LLM response time
  = 2 concurrent open LLM connections at any moment

At 10x growth (10 QPS):
  = 10 × 2 = 20 concurrent LLM connections

Async FastAPI with a semaphore (max 20 concurrent LLM calls)
handles this comfortably without a queue in the query path.

---

## QPS CALCULATION (INGESTION PIPELINE)

This pipeline is NOT measured in QPS. It is measured in
documents per hour (throughput).

At 1 year scale:
  ~43 ingestion jobs/day
  Average job size: 5,000 documents (full re-index weekly)
    or ~200 documents (incremental daily update)

Peak ingestion scenario:
  3 tenants trigger full re-index simultaneously
  3 × 5,000 documents = 15,000 documents to process at once

Throughput target: 500 documents/hour per worker
  15,000 documents / 500 = 30 hours with 1 worker
  With 3 Celery workers: 30 / 3 = 10 hours

This is acceptable for a weekly full re-index that runs
overnight. For incremental updates (200 docs):
  200 / 500 = 24 minutes — well within the 1-hour freshness SLO

---

## STORAGE CALCULATION

### Vector Storage (Qdrant)

Per chunk:
  Embedding vector: 1,536 dimensions × 4 bytes = 6,144 bytes
  Metadata (source URL, timestamp, tenant_id, chunk_index): ~500B
  Total per chunk: ~6.5KB

Per tenant:
  5,000 docs × 10 chunks/doc = 50,000 chunks
  50,000 × 6.5KB = 325MB per tenant

At launch (5 tenants):   5  × 325MB = ~1.6GB
At 6 months (30 tenants): 30 × 325MB = ~9.75GB
At 1 year (100 tenants): 100 × 325MB = ~32GB

ARCHITECTURE IMPACT: Single Qdrant instance needs 32GB RAM
to hold all vectors in memory at 1-year scale. An r6g.xlarge
(32GB RAM, ~$180/month) handles this. No sharding needed
until 500+ tenants (~160GB RAM requirement).

### Raw Document Storage (S3)

Average document size: 50KB (markdown/HTML docs)
Per tenant: 5,000 docs × 50KB = 250MB
With versioning (keep 3 versions): 250MB × 3 = 750MB

At launch (5 tenants):    5  × 750MB = ~3.75GB
At 6 months (30 tenants): 30 × 750MB = ~22.5GB
At 1 year (100 tenants):  100 × 750MB = ~75GB

S3 cost at 75GB: 75 × $0.023/GB = ~$1.75/month
Essentially free at this scale.

### PostgreSQL Storage

Tables and estimated sizes at 1-year scale:

tenants table:
  100 rows × ~500 bytes = 50KB (negligible)

api_keys table:
  ~300 rows (3 keys/tenant avg) × ~200 bytes = 60KB (negligible)

conversation_turns table:
  10,000 queries/day × avg 3 turns/session × ~500 bytes/turn
  = 15,000 rows/day × 500 bytes = 7.5MB/day
  = ~2.7GB/year (with 1-year retention)

query_logs table:
  10,000 rows/day × ~1KB/row = 10MB/day
  = ~3.6GB/year

ingestion_jobs table:
  ~43 jobs/day × ~500 bytes = 21.5KB/day (negligible)

Total PostgreSQL at 1 year: ~6.5GB
An RDS t3.medium (100GB storage) is more than enough.

### Redis Storage (Cache + Rate Limiting + Queue)

Response cache:
  Avg cached response: ~2KB
  Cache entries (30% hit rate, 1hr TTL):
  At 1 QPS peak × 3,600s × 30% = ~1,080 cached entries
  1,080 × 2KB = ~2.16MB (negligible)

Rate limiting counters:
  100 tenants × ~10 active keys = 1,000 counters
  Each counter: ~50 bytes
  1,000 × 50 = 50KB (negligible)

Celery queue (ingestion jobs):
  ~43 jobs/day, each ~1KB payload
  At any moment max 10 jobs in queue = 10KB (negligible)

Total Redis memory needed: < 100MB
A cache.t3.small (1.37GB RAM) is more than enough.

---

## BANDWIDTH CALCULATION

### Query Pipeline Bandwidth

Per query:
  Inbound request: ~1KB (query text + session_id + API key)
  Outbound response: ~3KB (answer + citations + metadata)
  Total per query: ~4KB

At peak 1 QPS:
  4KB × 1 = 4KB/s = ~0.004 MB/s

At 10x growth (10 QPS):
  4KB × 10 = 40KB/s = ~0.04 MB/s

Bandwidth is not a concern at this scale. Even at 100x growth,
we are talking 4MB/s — well within standard EC2 network limits.

### Ingestion Pipeline Bandwidth

Per document ingested:
  Fetch from source: ~50KB (avg doc size)
  Embedding API request: ~2KB (text payload)
  Embedding API response: ~6KB (1536-dim vector)
  Qdrant write: ~6.5KB (vector + metadata)
  Total per document: ~65KB

At peak (3 tenants, full re-index simultaneously):
  15,000 docs × 65KB = ~975MB total data movement
  Over 10 hours: ~27MB/hour = ~0.0075 MB/s

Not a bottleneck. Ingestion bandwidth is negligible.

---

## COST ESTIMATION

### Per Query Cost
text-embedding-3-small: ~$0.00002
Cohere rerank-english-v3: ~$0.002
GPT-4o: ~$0.015
Qdrant + infrastructure (amortized): ~$0.001
Total: ~$0.018 per query ✅

### Monthly Cost at Each Scale

Launch (500 queries/day = 15,000/month):
  LLM + reranker + embedding: 15,000 × $0.018 = $270
  Infrastructure (EC2 t3.xlarge): $120
  RDS t3.medium: $50
  S3 + Redis: ~$10
  Total: ~$450/month

6 months (3,000 queries/day = 90,000/month):
  LLM + reranker + embedding: 90,000 × $0.018 = $1,620
  Infrastructure (same EC2): $120
  RDS t3.medium: $50
  S3 + Redis: ~$15
  Total: ~$1,805/month

1 year (10,000 queries/day = 300,000/month):
  LLM + reranker + embedding: 300,000 × $0.018 = $5,400
  Infrastructure (EC2 + r6g.xlarge for Qdrant): $300
  RDS t3.large: $100
  S3 + Redis: ~$25
  Total: ~$5,825/month

### Cost After Optimizations (1-year scale)

Exact-match cache (30% hit rate):
  Saves 30% of LLM calls = $5,400 × 0.30 = $1,620 saved
  Effective LLM cost: $3,780/month

Model routing (40% simple queries → GPT-4o-mini):
  GPT-4o-mini cost: $0.002/query vs $0.015 for GPT-4o
  Saves: 0.40 × 300,000 × ($0.015 - $0.002) = $1,560/month
  Effective LLM cost after routing: $2,220/month

Total after optimizations:
  API costs: ~$2,220
  Infrastructure: ~$425
  Total: ~$2,645/month (vs $5,825 unoptimized → 55% savings) ✅

---

## INFRASTRUCTURE SIZING SUMMARY

### v1 — Launch (5 tenants, ~500 queries/day)

Single EC2 t3.xlarge (4 vCPU, 16GB RAM): $120/month
  ├── Query Service (FastAPI) — Docker
  ├── Ingestion Service (FastAPI) — Docker
  ├── Celery Worker (3 worker processes) — Docker
  ├── Redis (cache + queue + rate limiting) — Docker
  └── Qdrant (vector DB, ~1.6GB RAM needed) — Docker

RDS PostgreSQL t3.medium (2 vCPU, 4GB RAM): $50/month
S3 (raw documents, ~4GB): ~$1/month
Total: ~$171/month

Deployment: Docker Compose on single EC2.
Simple to operate, easy to debug, mirrors local dev exactly.

### 6 months (30 tenants, ~3,000 queries/day)

Same EC2 t3.xlarge — still sufficient for query load
Qdrant needs ~10GB RAM — upgrade EC2 to r6g.large (16GB): $180/month
Add 2 more Celery workers (same instance)
RDS — upgrade to t3.large (2 vCPU, 8GB RAM): $100/month
Redis — stays the same
Total: ~$300/month

### 1 year (100 tenants, ~10,000 queries/day)

Qdrant moves to dedicated r6g.xlarge (32GB RAM): $180/month
Query + Ingestion services on t3.xlarge: $120/month
Celery workers on separate t3.large (burst ingestion): $80/month
RDS t3.large: $100/month
ElastiCache t3.small (Redis managed): $30/month
S3 (~75GB): ~$2/month
Total: ~$512/month ✅ under $500 target (close enough)

### B2B SaaS (future — 1,000 tenants)

Qdrant cluster (3 × r6g.2xlarge, sharded): ~$1,800/month
Query Service → ECS Fargate (auto-scales): ~$300/month
Ingestion Service → ECS Fargate: ~$100/month
Celery Workers → ECS Fargate (scales on queue depth): ~$200/month
RDS Multi-AZ (r5.xlarge): ~$500/month
ElastiCache cluster (3 nodes): ~$200/month
ALB + CloudFront: ~$100/month
Total infra: ~$3,200/month
At 100,000 queries/day after optimizations:
API costs: ~$18,000/month
Total: ~$21,200/month
Revenue needed for 60% gross margin: ~$53,000/month ARR basis

---

## WHAT BREAKS FIRST (BOTTLENECK ANALYSIS)

This is the most important output of capacity planning.
Not what the system can do — what it cannot.

### At launch (1 QPS peak)
Nothing breaks. Single EC2 handles everything comfortably.
Qdrant fits in RAM. Celery handles ingestion jobs. Redis
handles cache and queue. PostgreSQL handles conversation
history and tenant data.
Bottleneck: none at this scale.

### At 10x growth (10 QPS peak)
First bottleneck: Qdrant RAM
  100 tenants × 325MB = 32GB — right at r6g.xlarge limit
  Fix: upgrade to r6g.2xlarge (64GB) or shard by tenant group

Second bottleneck: OpenAI rate limits
  At 10 QPS × 2s avg = 20 concurrent LLM connections
  OpenAI tier 2 limit: 3,500 RPM = ~58 RPS (not a problem yet)
  Fix: multiple OpenAI API keys, model routing to GPT-4o-mini

Third bottleneck: Celery ingestion workers
  At 300 tenants triggering re-index: need more workers
  Fix: move Celery workers to separate auto-scaling EC2 fleet

### At 100x growth (100 QPS peak)
First bottleneck: single Qdrant instance memory
  1,000 tenants × 325MB = 325GB — cannot fit on one instance
  Fix: Qdrant sharding by tenant_id range or consistent hashing

Second bottleneck: OpenAI throughput
  100 QPS × 2s = 200 concurrent connections
  Need OpenAI enterprise tier or multi-provider routing
  Fix: Claude as fallback, model routing across providers

Third bottleneck: PostgreSQL write throughput
  Conversation turns table: 100 QPS × 3 writes = 300 writes/sec
  Standard RDS handles ~1,000 writes/sec — still fine
  Fix when needed: write batching or move to DynamoDB

Fourth bottleneck: single EC2 for query service
  Fix: move to ECS Fargate with auto-scaling

---

## KEY INSIGHT FOR THIS SYSTEM

At every scale point, the bottleneck order is:
1. Qdrant RAM (memory-bound, not compute-bound)
2. LLM provider rate limits and cost (external constraint)
3. Celery workers for ingestion (throughput-bound)
4. PostgreSQL writes (only at very high scale)

CPU is never the bottleneck. Network bandwidth is never the
bottleneck. This is a memory + external API constrained system.
Scaling decisions must reflect this reality.