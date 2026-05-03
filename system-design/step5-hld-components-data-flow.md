# Step 5 — High Level Design (HLD)

---

## SYSTEM OVERVIEW

This system is a production-grade RAG pipeline that turns any
technical knowledge base into an accurate, grounded, source-cited
AI assistant. It is exposed via two interfaces — a REST API for
human developers and an MCP server for AI coding agents.

The two most important architectural boundaries in this system:

1. Indexing pipeline and query pipeline are completely separate
   services. They scale on different axes and share nothing except
   the storage layer (Qdrant + S3 + PostgreSQL).

2. MCP server is a separate process that speaks the MCP protocol
   and delegates all RAG logic to the query service via internal
   HTTP. Zero duplicate logic.

---

## CORE COMPONENTS

### 1. Ingestion Service (FastAPI — port 8001)
Receives ingestion job requests from tenant admins.
Validates the source (URL, GitHub repo, PDF, Slack export).
Creates a job record in PostgreSQL with status "pending".
Enqueues the job to Celery via Redis queue.
Returns job_id immediately — does not wait for ingestion to finish.
Exposes: POST /ingest, GET /ingest/{job_id}

### 2. Celery Workers (Ingestion Pipeline)
Polls Redis queue for pending ingestion jobs.
For each job:
  → Connector fetches raw content from source
  → Cleaner strips noise (HTML tags, boilerplate, nav menus)
  → Chunker splits content into chunks (heading-aware + semantic)
  → Embedder generates dense vector (text-embedding-3-small)
  → Sparse encoder generates sparse vector (FastSPLADE)
  → Both vectors + metadata written to Qdrant (tenant namespace)
  → Raw document backed up to S3 (source of truth)
  → Job status updated to "completed" in PostgreSQL
Runs completely independently from query service.
3 worker processes at launch, scales horizontally.

### 3. Connectors (inside Celery Workers)
Factory pattern — one interface, multiple implementations.
Each connector knows how to fetch from one specific source type.

ConnectorFactory
  → DocsConnector      (crawls docs sites via sitemap or URL list)
  → GitHubConnector    (fetches markdown, README, code files)
  → PDFConnector       (extracts text from PDF files)
  → SlackConnector     (parses JSON export files)

Adding a new connector (Confluence, Notion) requires:
  → implement the Connector interface
  → register in ConnectorFactory
  → zero changes to the rest of the pipeline

### 4. Query Service (FastAPI — port 8000)
The core of the system. Handles all query requests from humans
(REST API) and from the MCP server (internal HTTP).
Every query goes through this exact pipeline:

  Step 1: Authenticate request (API key → tenant_id)
  Step 2: Check Redis exact-match cache
          → HIT: return cached response immediately
          → MISS: continue to step 3
  Step 3: Rewrite query (expand abbreviations, fix ambiguity)
  Step 4: Generate dense + sparse vectors in parallel (asyncio)
          → text-embedding-3-small for dense (~100ms)
          → FastSPLADE for sparse (~30ms)
          → both finish in ~100ms (parallel not sequential)
  Step 5: Single Qdrant hybrid search call (~200ms)
          → dense + sparse retrieved in parallel internally
          → RRF fusion done inside Qdrant
          → top-20 chunks returned
  Step 6: Cohere reranker (~200ms)
          → top-20 → reranked → top-5 passed to LLM
  Step 7: Fetch last 3 conversation turns from PostgreSQL (~30ms)
          → keyed by session_id
  Step 8: Build context window
          → system prompt (~500 tokens)
          → top-5 chunks (~4,000 tokens)
          → last 3 turns (~600 tokens)
          → current query (~500 tokens)
          → check token count via tiktoken
          → drop lowest-ranked chunks if over 6,000 token cap
  Step 9: GPT-4o streaming call (~1,500ms, first token < 500ms)
          → grounding check: every claim tied to a source chunk
          → if answer not in chunks → "I don't know"
  Step 10: Save response to Redis cache (TTL: 1hr)
           Save conversation turn to PostgreSQL
           Log full trace to LangSmith (async, non-blocking)
           Return response + citations to caller

Exposes: POST /query, POST /sessions, DELETE /sessions/{id},
         GET /health, GET /metrics

### 5. MCP Server (separate process — port 8002)
Speaks MCP protocol over SSE (hosted) or stdio (local).
Thin protocol translation layer — zero RAG logic lives here.
Exposes two MCP tools:

Tool 1: search_knowledge_base(query, session_id)
  → translates MCP tool call to internal HTTP POST /query
  → returns grounded answer + source citations to agent

Tool 2: fetch_and_query_online_docs(url, query)
  → fetches live URL content
  → builds temporary in-memory index (not persisted to Qdrant)
  → runs same retrieval + generation pipeline
  → caches result in Redis for 30 minutes (TTL)
  → returns answer + source URL to agent

Why separate process:
  MCP uses SSE/stdio protocol, not HTTP
  Long-lived agent connections behave differently from HTTP requests
  Query service failures do not kill active MCP connections
  MCP service failures do not affect REST API users

### 6. Qdrant (Vector Database)
Self-hosted on EC2. One collection per tenant.
Each chunk stored with two vectors:
  Dense vector: 1536 dimensions (text-embedding-3-small)
  Sparse vector: SPLADE format (FastSPLADE)
Hybrid search (dense + sparse) runs in parallel internally.
RRF fusion happens inside Qdrant before results returned.
Metadata per chunk: source_url, timestamp, tenant_id,
  document_title, chunk_index, source_type, version

At launch: ~1.6GB RAM needed (5 tenants)
At 1 year: ~32GB RAM needed (100 tenants)
Infrastructure: r6g.xlarge (32GB RAM) at 1-year scale

### 7. PostgreSQL (RDS)
Source of truth for all relational and transactional data.
CP system — strong consistency required for all tables here.

Tables:
  tenants          → tenant_id, name, plan, created_at
  api_keys         → key_hash, tenant_id, scopes, created_at
  ingestion_jobs   → job_id, tenant_id, source, status,
                     docs_processed, errors, created_at
  conversation_turns → session_id, tenant_id, role, content,
                       tokens, created_at
  sessions         → session_id, tenant_id, created_at,
                     expires_at (1hr TTL)

Row Level Security (RLS) on all tables — tenant_id enforced
at DB layer not just application layer.

### 8. Redis
Three separate responsibilities, same Redis instance:

Response cache:
  Key: cache:{tenant_id}:{sha256(query)}
  Value: full response JSON
  TTL: 1 hour

Rate limiting:
  Key: ratelimit:{tenant_id}:{minute_window}
  Value: request count (atomic INCR)
  TTL: 60 seconds

Celery job queue:
  Ingestion jobs enqueued here
  Celery workers poll this queue
  Failed jobs retry with exponential backoff

### 9. S3 (Raw Document Storage)
Source of truth for all raw documents.
If Qdrant is ever lost or corrupted, re-run ingestion from S3.
Path pattern: s3://bucket/tenant-{id}/docs/{doc_hash}/{version}
Versioning enabled — keeps last 3 versions of every document.
Cost at 1-year scale: ~$2/month (negligible).

### 10. LangSmith (Observability)
Every query is logged asynchronously (non-blocking).
Full trace per query: input, rewritten query, retrieved chunks,
reranker scores, context sent to LLM, LLM response, latency
breakdown, cost, cache hit/miss, faithfulness score (async).
Used for: debugging, prompt iteration, quality monitoring.

### 11. Prometheus + Grafana (Metrics + Dashboards)
Prometheus scrapes metrics from query service and ingestion service.
Metrics tracked:
  QPS, p50/p95/p99 latency per endpoint
  Cache hit rate per tenant
  LLM cost per query per tenant
  Reranker score distribution
  Ingestion job success/failure rate
  Qdrant RAM usage
  Concurrent open LLM connections

Grafana dashboards:
  Service health (for engineers)
  Quality metrics (faithfulness, relevance trends)
  Cost per tenant (for billing awareness)
  Ingestion pipeline health

---

## DATA FLOW — INGESTION

1. Tenant admin calls POST /ingest with source details
2. Ingestion Service validates request, creates job in PostgreSQL
3. Job enqueued to Redis (Celery queue)
4. Returns job_id immediately to caller
5. Celery worker picks up job from queue
6. Connector fetches raw content from source
7. Cleaner removes noise, normalizes format
8. Chunker splits into chunks (heading-aware strategy)
9. For each chunk (in parallel batches):
   a. text-embedding-3-small generates dense vector
   b. FastSPLADE generates sparse vector
   c. Both vectors + metadata written to Qdrant
   d. Raw document written to S3
10. Job status updated to "completed" in PostgreSQL
11. Tenant admin polls GET /ingest/{job_id} to check status

Freshness handling runs on a schedule:
  Incremental re-index: daily (only changed/new docs)
  Full re-index: weekly (entire knowledge base rebuilt)
  Both triggered as Celery scheduled tasks (Celery Beat)

---

## DATA FLOW — QUERY (HAPPY PATH)

1. User or agent sends POST /query with:
   { query, session_id, tenant_id (from API key) }

2. Query Service authenticates API key → derives tenant_id
   Rate limit check (Redis) → reject if exceeded

3. Redis exact-match cache check
   HIT → return cached response immediately (skip to step 11)
   MISS → continue

4. Query rewriter expands abbreviations, fixes ambiguity
   e.g. "how do i set up auth?" →
   "how do I configure authentication in {product}?"

5. Parallel vector generation (asyncio):
   text-embedding-3-small → dense vector (~100ms)
   FastSPLADE → sparse vector (~30ms)
   Both complete in ~100ms

6. Single Qdrant hybrid search call (~200ms):
   Dense + sparse retrieved in parallel internally
   RRF fusion inside Qdrant
   top-20 chunks returned with scores

7. Cohere reranker (~200ms):
   top-20 chunks → cross-encoder reranking → top-5

8. Fetch last 3 conversation turns from PostgreSQL
   keyed by session_id (~30ms, runs in parallel with step 7)

9. Build context window:
   system prompt + top-5 chunks + last 3 turns + query
   tiktoken check → drop lowest chunks if over 6,000 tokens

10. GPT-4o streaming call:
    First token < 500ms
    Full response ~1,500ms
    Grounding check: if answer not in chunks → "I don't know"
    Response includes: answer text + source URLs + confidence

11. Async post-processing (non-blocking, after response sent):
    Save response to Redis cache (TTL: 1hr)
    Save turn to PostgreSQL (conversation_turns table)
    Log full trace to LangSmith
    Emit metrics to Prometheus

Total latency at p50: ~500ms
Total latency at p95: ~2s
First token to user: < 500ms (streaming)

---

## DATA FLOW — MCP TOOL CALL

1. Agent (Cursor/Claude Code) calls MCP tool:
   search_knowledge_base(query="how do I configure X",
                         session_id="abc123")

2. MCP Server receives tool call over SSE/stdio
3. Translates to internal HTTP POST /query to Query Service
4. Query Service runs full RAG pipeline (same as above)
5. Response returned to MCP Server
6. MCP Server formats as MCP tool response
7. Agent receives: answer + source citations
8. Agent uses citations to write correct, grounded code

For fetch_and_query_online_docs:
1. Agent calls tool with URL + query
2. MCP Server fetches URL content (requests + BeautifulSoup)
3. Chunks content, generates embeddings in-memory
4. Runs same retrieval + generation pipeline
5. Caches result in Redis for 30 minutes
6. Returns answer + source URL to agent

---

## STRATEGY PATTERN SUMMARY

Every swappable component sits behind an interface.
Changing providers is a config change not a code change.

LLMStrategy:
  Default → GPT-4o (OpenAI)
  Routing → GPT-4o-mini for simple queries
  Future  → Claude 3.5 Sonnet, Gemini 1.5 Pro

EmbeddingStrategy:
  Default → text-embedding-3-small (OpenAI)
  Alternative → Cohere embed-english-v3

VectorDBStrategy:
  Default → Qdrant self-hosted
  Alternative → Qdrant Cloud, Pinecone

RerankerStrategy:
  Default → Cohere rerank-english-v3
  Alternative → BGE reranker (local, free)

QueueStrategy:
  Default → Celery + Redis
  Production → SQS + ECS workers

ConnectorStrategy (Factory pattern):
  DocsConnector, GitHubConnector, PDFConnector, SlackConnector

---

## CIRCUIT BREAKER SUMMARY

Every external dependency has a circuit breaker.
System never returns a blank error.

OpenAI API:
  Opens after 5 failures in 60s
  Fallback: return top-5 chunks without LLM generation
  Tell user: "LLM temporarily unavailable, here are
  relevant docs"

Qdrant:
  Opens after 3 failures in 30s
  Fallback: this should not happen in normal operation
  since Qdrant is self-hosted on same infrastructure
  Last resort: return "search temporarily unavailable"

Cohere Reranker:
  Opens after 3 failures in 30s
  Fallback: skip reranking, pass raw top-5 directly to LLM

Redis:
  Opens after 3 failures in 30s
  Fallback: bypass cache, query pipeline directly
  Rate limiting disabled temporarily (log warning)

---

## DEPLOYMENT ARCHITECTURE (v1)

Single EC2 t3.xlarge (Docker Compose):
  query-service     → FastAPI, port 8000
  ingestion-service → FastAPI, port 8001
  mcp-server        → FastAPI/MCP, port 8002
  celery-worker     → 3 worker processes
  celery-beat       → scheduler for re-index jobs
  redis             → port 6379
  qdrant            → port 6333

Separate managed services:
  RDS PostgreSQL    → t3.medium
  S3                → raw document storage

External services:
  OpenAI API        → embeddings + generation
  Cohere API        → reranking
  LangSmith         → observability traces
  Prometheus        → metrics scraping
  Grafana           → dashboards

Everything runs via Docker Compose locally and on EC2.
Local dev environment is identical to production.







