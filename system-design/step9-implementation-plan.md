# Step 9 — Implementation Plan

It is a phased engineering plan where
each phase has clear entry criteria, exit criteria, and deliverables.
Code only starts after system design is complete. Each phase builds
on the previous one without breaking it.

The implementation follows evaluation-driven development:
define quality thresholds before writing code, measure after every
phase, gate the next phase on meeting those thresholds.

---

## DESIGN PATTERNS USED IN THIS SYSTEM

Before phases, here is the complete pattern map. Every pattern
decision is made once here and never revisited mid-implementation.

### Strategy Pattern (Provider Swappability)
Every external provider is behind an interface. Switching providers
is a config change, not a code change. This is the most important
architectural decision in the entire codebase.

LLMStrategy:
  Interface:   generate(messages, stream) → response
  Default:     OpenAILLM (GPT-4o)
  Routing:     GPT-4o-mini for simple, GPT-4o for complex
  Fallback:    ClaudeLLM (via circuit breaker)

EmbeddingStrategy:
  Interface:   embed(texts) → vectors
  Default:     OpenAIEmbedding (text-embedding-3-small)
  Fallback:    LocalEmbedding (all-MiniLM, only on API failure)

VectorDBStrategy:
  Interface:   upsert(chunks), hybrid_search(query, sparse, tenant) → chunks
  Default:     QdrantDB (self-hosted)
  Alternative: PineconeDB (one-line config change)

RerankerStrategy:
  Interface:   rerank(query, chunks, top_n) → ranked_chunks
  Default:     CohereReranker (rerank-english-v3)
  Fallback:    PassthroughReranker (returns top-k by retrieval score)

QueueStrategy:
  Interface:   enqueue(job), dequeue() → job, ack(job_id)
  Default:     CeleryRedisQueue (already in stack, zero extra cost)
  Production:  SQSQueue (when guaranteed persistence is required)

### Factory Pattern (Connector Extensibility)
ConnectorFactory routes document sources to the right connector.
Adding a new source requires implementing one interface and
registering it in the factory. Zero changes to the pipeline.

ConnectorFactory → DocsConnector | GitHubConnector | PDFConnector  | SlackConnector

### Repository Pattern (Storage Abstraction)
Every data access layer sits behind a Repository interface.
Migrating from PostgreSQL conversation history to DynamoDB
(when it eventually makes sense at scale) is a config change
not a rewrite. This is the Dependency Inversion Principle applied.

ConversationRepository:  get_turns(session_id) | save_turn(turn)
ChunkRepository:         get_chunks(doc_id)    | delete_chunks(doc_id)
IngestionJobRepository:  get_job(job_id)        | update_status(job_id, status)

### Circuit Breaker Pattern (Reliability)
One CircuitBreaker instance per external dependency.
States: CLOSED → OPEN (5 failures/60s) → HALF_OPEN (30s) → CLOSED
Every circuit breaker has a defined fallback behavior.

OpenAI API:     OPEN → return raw retrieved chunks, tell user LLM unavailable
Qdrant:         OPEN → BM25-only fallback retrieval
Cohere:         OPEN → PassthroughReranker (skip reranking, top-k by score)
Redis:          OPEN → bypass cache, query pipeline directly

### Observer Pattern (Async Post-Processing)
After every query response is streamed to the user, three async
non-blocking operations fire: cache write, LangSmith trace, and
Prometheus metric emission. None of these block the response.

QueryObservers:
  CacheWriteObserver  → writes response to Redis (TTL: 1hr)
  TraceObserver       → sends full trace to LangSmith
  MetricsObserver     → emits latency, cost, tokens to Prometheus

### Builder Pattern (Context Window Construction)
Building the LLM context window has strict ordering and token budget
rules. A Builder pattern enforces these rules and prevents invalid
context from being constructed.

ContextWindowBuilder:
  .set_system_prompt(prompt)      # ~500 tokens, fixed, cached
  .add_chunks(chunks, max=4000)   # top-5 chunks, enforces token cap
  .add_conversation(turns, max=600) # last 3 turns
  .add_query(query)               # current user query
  .build() → ContextWindow        # validates token budget via tiktoken
                                  # drops lowest-ranked chunks if over 6000

---

## PHASE 0 — FOUNDATION (Week 1)

### Entry Criteria
System design Steps 1-10 are complete and reviewed.
Docker + Python environment confirmed working locally.

### What Gets Built
Complete project scaffolding, Docker Compose setup, and all
interface definitions. Zero business logic. Zero LLM calls.
Zero vector DB writes.

**Folder structure (derived from LLD, not guessed):**
```
kapa-inspired-rag-mcp/
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── backend/
│   ├── query_service/
│   │   ├── main.py               # FastAPI app, routes only
│   │   ├── api/
│   │   │   ├── routes/
│   │   │   │   ├── query.py      # POST /query, POST /sessions
│   │   │   │   └── health.py     # GET /health, GET /metrics
│   │   ├── core/
│   │   │   ├── pipeline.py       # Query pipeline orchestrator
│   │   │   ├── context_builder.py # Builder pattern
│   │   │   └── circuit_breaker.py # Circuit breaker implementation
│   │   ├── strategies/
│   │   │   ├── base.py           # All Strategy interfaces
│   │   │   ├── llm/
│   │   │   │   ├── openai_llm.py
│   │   │   │   └── claude_llm.py
│   │   │   ├── embedding/
│   │   │   │   └── openai_embedding.py
│   │   │   ├── vectordb/
│   │   │   │   ├── qdrant_db.py
│   │   │   │   └── pinecone_db.py
│   │   │   └── reranker/
│   │   │       ├── cohere_reranker.py
│   │   │       └── passthrough_reranker.py
│   │   ├── repositories/
│   │   │   ├── base.py           # Repository interfaces
│   │   │   ├── conversation_repo.py
│   │   │   └── session_repo.py
│   │   └── observers/
│   │       ├── base.py           # Observer interface
│   │       ├── cache_observer.py
│   │       ├── trace_observer.py
│   │       └── metrics_observer.py
│   │
│   ├── ingestion_service/
│   │   ├── main.py               # FastAPI app
│   │   ├── api/routes/
│   │   │   └── ingest.py         # POST /ingest, GET /ingest/{job_id}
│   │   ├── connectors/
│   │   │   ├── base.py           # ConnectorStrategy interface
│   │   │   ├── factory.py        # ConnectorFactory
│   │   │   ├── docs_connector.py
│   │   │   ├── github_connector.py
│   │   │   ├── pdf_connector.py
│   │   │   └── slack_connector.py
│   │   ├── pipeline/
│   │   │   ├── preprocessor.py   # Clean, normalize text
│   │   │   ├── chunker.py        # Semantic sliding window chunker
│   │   │   └── freshness.py      # Incremental vs full re-index logic
│   │   ├── workers/
│   │   │   └── celery_worker.py  # Celery tasks
│   │   └── repositories/
│   │       └── ingestion_job_repo.py
│   │
│   └── mcp_server/
│       ├── main.py               # MCP server, SSE transport
│       └── tools/
│           ├── search_kb.py      # search_knowledge_base tool
│           └── fetch_online.py   # fetch_and_query_online_docs tool
│
├── infra/
│   ├── prometheus.yml
│   └── grafana/
│
└── eval/
├── golden_set.json           # 100+ query-answer pairs
├── run_ragas.py              # evaluation runner
└── ci_gate.py                # CI quality gate script
```

**Docker Compose (all services):**

```yaml
services:
  query-service:
    build: ./backend/query_service
    ports: ["8000:8000"]
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - COHERE_API_KEY=${COHERE_API_KEY}
      - QDRANT_URL=http://qdrant:6333
      - REDIS_URL=redis://redis:6379
      - POSTGRES_URL=${POSTGRES_URL}

  ingestion-service:
    build: ./backend/ingestion_service
    ports: ["8001:8001"]

  celery-worker:
    build: ./backend/ingestion_service
    command: celery -A workers.celery_worker worker --loglevel=info
    environment: [same as ingestion-service]

  celery-beat:
    build: ./backend/ingestion_service
    command: celery -A workers.celery_worker beat --loglevel=info

  mcp-server:
    build: ./backend/mcp_server
    ports: ["8002:8002"]

  qdrant:
    image: qdrant/qdrant:latest
    ports: ["6333:6333"]
    volumes: [qdrant_data:/qdrant/storage]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    command: redis-server --maxmemory 2gb --maxmemory-policy allkeys-lru

  prometheus:
    image: prom/prometheus:latest
    ports: ["9090:9090"]
    volumes: [./infra/prometheus.yml:/etc/prometheus/prometheus.yml]

  grafana:
    image: grafana/grafana:latest
    ports: ["3000:3000"]
```

### All Strategy Interfaces Defined (base.py)
All interfaces are written in Phase 0. No implementations yet.
This enforces Dependency Inversion from day one — the pipeline
is wired to interfaces before any concrete class exists.

```python
from abc import ABC, abstractmethod

class LLMStrategy(ABC):
    @abstractmethod
    async def generate(self, messages, stream=False) -> dict: pass

class EmbeddingStrategy(ABC):
    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]: pass

class VectorDBStrategy(ABC):
    @abstractmethod
    async def upsert(self, chunks: list[dict], tenant_id: str) -> None: pass

    @abstractmethod
    async def hybrid_search(
        self, dense_vec, sparse_vec, tenant_id: str, top_k: int
    ) -> list[dict]: pass

class RerankerStrategy(ABC):
    @abstractmethod
    async def rerank(
        self, query: str, chunks: list[dict], top_n: int
    ) -> list[dict]: pass

class ConnectorStrategy(ABC):
    @abstractmethod
    def can_handle(self, source_type: str) -> bool: pass

    @abstractmethod
    async def fetch(self, source_url: str, metadata: dict) -> list[dict]: pass

class ConversationRepository(ABC):
    @abstractmethod
    async def get_turns(self, session_id: str, limit: int) -> list[dict]: pass

    @abstractmethod
    async def save_turn(self, session_id: str, turn: dict) -> None: pass
```

### Exit Criteria
`docker compose up` works.
All services start healthy.
All interfaces defined, zero implementations.
All environment variables documented in .env.example.

---

---

## EMPIRICAL DECISION FRAMEWORK

Before locking in any strategy in this project, we measure it.
This applies to chunking, retrieval configuration, and generation
parameters.
The mindset I follow: every architectural decision that affects
quality is treated as a hypothesis to be tested, not an assumption
to be trusted.

The measurement pipeline:
  1. Build a small golden evaluation set per source type (30-50 Q&A pairs)
  2. Index with each candidate strategy
  3. Measure Precision@5, Recall@5, MRR for retrieval decisions
  4. Measure Faithfulness, Context Precision, Context Recall for generation
  5. Pick the winner empirically
  6. Document the comparison with real numbers in TRADEOFFS.md

This framework runs three times:
  Phase 1 → chunking strategy selection per source type
  Phase 2 → retrieval configuration selection (top-K, reranker, fusion)
  Phase 4 → generation parameter tuning (model, context size, prompt)

Each decision is locked in with data

---

## PHASE 1 — INGESTION PIPELINE (Week 2)

### Entry Criteria
Phase 0 complete. Docker Compose running. All interfaces defined.

### What Gets Built
The full ingestion pipeline from source URL to Qdrant. By end of
this phase, you can POST a docs URL, Celery processes it, and chunks
appear in Qdrant queryable by tenant namespace.

**Components built in order:**

**1. PostgreSQL Schema**
```sql
CREATE TABLE tenants (
  tenant_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  plan        VARCHAR(20) DEFAULT 'free',
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE api_keys (
  key_hash    TEXT PRIMARY KEY,
  tenant_id   UUID REFERENCES tenants(tenant_id),
  scopes      TEXT[],
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE ingestion_jobs (
  job_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id        UUID REFERENCES tenants(tenant_id),
  source_url       TEXT,
  source_type      VARCHAR(20),
  status           VARCHAR(20) DEFAULT 'pending',
  docs_processed   INT DEFAULT 0,
  docs_failed      INT DEFAULT 0,
  error_message    TEXT,
  created_at       TIMESTAMPTZ DEFAULT NOW(),
  completed_at     TIMESTAMPTZ
);

-- RLS on all tables
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_jobs ENABLE ROW LEVEL SECURITY;
```

**2. ConnectorFactory + DocsConnector (first connector)**
Factory returns the right connector for a source type.
DocsConnector crawls a docs site via sitemap, returns clean text.
Preprocessing: strip HTML, remove nav/footer, normalize whitespace.
This is the hardest connector — build it first.

**3. Chunker (Semantic Sliding Window)**
Chunk size: 512 tokens for factual content.
Overlap: 15% (prevent splitting key phrases).
Split priority: paragraph → sentence → word.
Each chunk carries metadata: source_url, tenant_id, chunk_index,
document_title, timestamp, doc_version.

**4. OpenAIEmbedding (EmbeddingStrategy implementation)**
Batch embedding — never one chunk at a time.
Batch size: 100 chunks per API call.
10-50x cheaper than per-chunk calls.
Embedding cache via Redis (sha256(text) → vector, TTL: 7 days).

**5. Sparse Vector Generation (FastSPLADE)**
Each chunk generates both dense and sparse vectors.
Sparse vector stored alongside dense in Qdrant.
FastSPLADE runs inside the Celery worker — no extra service.

**6. QdrantDB (VectorDBStrategy implementation)**
One collection per tenant: `tenant_{tenant_id}`
Each point: {id, dense_vector, sparse_vector, payload}
Payload: source_url, title, content, chunk_index, tenant_id,
         timestamp, doc_version, source_type

**7. Celery Worker Pipeline**
Full async chain: fetch → preprocess → chunk → embed →
sparse encode → upsert to Qdrant → backup to S3 → update job status.
Idempotent: chunk ID = sha256(tenant_id + source_url + chunk_index).
Upsert not insert — re-running is safe.

**8. POST /ingest endpoint**
Validates source URL → creates job in PostgreSQL →
enqueues to Celery queue → returns job_id immediately (202 Accepted).
GET /ingest/{job_id} → returns job status.

**9. Freshness: Incremental + Full Re-index**
Incremental: daily (Celery Beat) — detect changed documents via
URL fingerprinting, re-embed only changed chunks.
Full re-index: weekly — rebuild entire tenant namespace from scratch,
handle deletions (ghost content problem documented in pre-mortem).
Both documented in system design with explicit tradeoffs.

**10. S3 Raw Document Storage**
Every raw document backed up before processing.
Path: `s3://bucket/tenant-{id}/docs/{doc_hash}/{version}/raw.{ext}`
Source of truth — if Qdrant is lost, re-index from S3.

### Key Design Pattern: Factory + Strategy Together
```python
class ConnectorFactory:
    _connectors = [
        DocsConnector(),
        GitHubConnector(),
        PDFConnector(),
        SlackConnector(),
    ]

    def get_connector(self, source_type: str) -> ConnectorStrategy:
        for connector in self._connectors:
            if connector.can_handle(source_type):
                return connector
        raise UnsupportedSourceError(source_type)
    # Adding a new connector: implement ConnectorStrategy,
    # append to _connectors. Zero other changes.
```

### Quality Gate
Ingest a 50-page docs site. Verify:
- All chunks appear in Qdrant with correct tenant namespace
- No chunk is in wrong tenant namespace (isolation test)
- Raw docs backed up to S3
- Job status correctly transitions pending → running → completed
- Re-running same ingestion is idempotent (no duplicate chunks)
- Incremental re-index only re-processes changed docs

### Exit Criteria
DocsConnector + GitHubConnector working.
Chunks queryable from Qdrant by tenant namespace.
Ingestion job status tracked in PostgreSQL.
Freshness pipeline (incremental + full) running on schedule.

### Phase 1 Sub-Phase: Chunking Strategy Selection (Before Locking In)

Before finalizing the chunker, we run an empirical comparison.
Different source types have fundamentally different structure.
One chunking strategy for all sources is the wrong default.

**Strategies compared per source type:**

Docs sites (HTML/Markdown):
  Candidate A: Sliding window 512 tokens, 15% overlap
  Candidate B: Heading-aware chunking (split at H1/H2/H3 boundaries)
  Hypothesis: heading-aware wins because docs sites have deliberate
  structure — each section is a self-contained concept.

GitHub repositories (README, markdown):
  Candidate A: Sliding window 512 tokens
  Candidate B: Heading-aware chunking
  Candidate C: Code-block-aware (preserve function/class boundaries)
  Hypothesis: heading-aware for markdown docs, code-block-aware
  for .py/.js files with actual code content.

PDFs:
  Candidate A: Sliding window after PyMuPDF extraction
  Candidate B: Hierarchical (summary → section → paragraph)
  Hypothesis: hierarchical wins for structured reports, sliding
  window wins for unstructured PDFs.

Slack exports:
  Candidate A: Fixed-size by message count (5 messages per chunk)
  Candidate B: Thread-aware (group entire thread as one chunk)
  Hypothesis: thread-aware wins because Slack conversations have
  logical units — a thread is a single discussion, not arbitrary text.

**Measurement process:**

Step 1: Index 3-5 representative documents per source type
        using each candidate strategy.
Step 2: Build 30 questions per source type with ground truth answers.
        These become part of the permanent golden evaluation set.
Step 3: Run classical IR evaluation — Precision@5, Recall@5, MRR.
        No RAGAS yet — we are testing retrieval only at this stage.
Step 4: Pick the winning strategy per source type based on Precision@5
        as the primary metric (signal-to-noise matters most here).
Step 5: Lock the winner into each connector's chunker.
        Document the comparison table in TRADEOFFS.md.

**Expected output (fill in with real numbers during implementation):**

Docs Connector — Chunking Strategy Comparison:
| Strategy            | Precision@5 | Recall@5 | MRR  |
|---------------------|-------------|----------|------|
| Sliding window 256  | ?           | ?        | ?    |
| Sliding window 512  | ?           | ?        | ?    |
| Heading-aware       | ?           | ?        | ?    |
Winner: [fill in after measurement]
Reason: [fill in with actual numbers]

GitHub Connector — Chunking Strategy Comparison:
[same table structure]

PDF Connector — Chunking Strategy Comparison:
[same table structure]

Slack Connector — Chunking Strategy Comparison:
[same table structure]

**Why different strategies per source type works architecturally:**

The ConnectorFactory pattern supports this natively. Each connector
owns its own chunking strategy — DocsConnector uses heading-aware,
SlackConnector uses thread-aware, etc. The ingestion pipeline does
not care which strategy was used. It receives chunks. The strategy
is encapsulated inside the connector.

This is the Open/Closed Principle applied to chunking:
new strategies are added by implementing a ChunkerStrategy interface
and injecting it into the connector. Zero changes to the pipeline.

class ChunkerStrategy(ABC):
    @abstractmethod
    def chunk(self, text: str, metadata: dict) -> list[Chunk]: pass

class HeadingAwareChunker(ChunkerStrategy):
    def chunk(self, text: str, metadata: dict) -> list[Chunk]: ...

class ThreadAwareChunker(ChunkerStrategy):
    def chunk(self, text: str, metadata: dict) -> list[Chunk]: ...

class DocsConnector(ConnectorStrategy):
    def __init__(self):
        self.chunker = HeadingAwareChunker()  # winner from measurement

---

## PHASE 2 — QUERY PIPELINE (Week 3)

### Entry Criteria
Phase 1 complete. Chunks in Qdrant. At least one tenant has
indexed documents.

### What Gets Built
The full query pipeline from POST /query to streamed response.
By end of this phase, you can query the knowledge base and get
a grounded, cited answer.

**Components built in order:**

**1. Session Management (PostgreSQL)**
```sql
CREATE TABLE sessions (
  session_id  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  tenant_id   UUID REFERENCES tenants(tenant_id),
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  expires_at  TIMESTAMPTZ NOT NULL
);

CREATE TABLE conversation_turns (
  id          BIGSERIAL PRIMARY KEY,
  session_id  UUID REFERENCES sessions(session_id),
  tenant_id   UUID NOT NULL,
  role        VARCHAR(10) NOT NULL,
  content     TEXT NOT NULL,
  tokens      INT,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_session_turns ON conversation_turns(session_id, created_at DESC);
```

**2. Redis Cache Layers**
Exact cache: `cache:{tenant_id}:{sha256(query)}` TTL: 3600s
Rate limiting: `ratelimit:{tenant_id}:{minute}` TTL: 60s

**3. Query Rewriter**
Rewrites conversational follow-up queries to standalone queries.
Uses GPT-4o-mini (cheap + fast, ~60ms).
Falls back to original query if rewriter fails.

**4. Parallel Vector + Sparse Embedding**
Both dense and sparse vectors generated in parallel via asyncio.
text-embedding-3-small (dense) + FastSPLADE (sparse) run together.
Total: ~100ms (not 130ms sequential).

```python
dense_vec, sparse_vec = await asyncio.gather(
    embedding_strategy.embed([query]),
    splade_encoder.encode(query),
    return_exceptions=True
)
```

**5. Qdrant Hybrid Search (Parallel Internally)**
Single Qdrant API call with both dense and sparse vectors.
Qdrant executes dense and sparse retrieval in parallel internally.
RRF fusion built into Qdrant — no custom merge code.
Top-20 chunks returned.

**6. Cohere Reranker**
Top-20 → cross-encoder reranking → top-5.
CohereReranker implements RerankerStrategy.
Fallback: PassthroughReranker (top-5 by retrieval score).
Circuit breaker: opens after 3 failures, fallback activates.

**7. ContextWindowBuilder (Builder Pattern)**
Assembles the LLM context window in strict order.
Enforces 6000 token hard cap via tiktoken.
Drops lowest-ranked chunks first if over budget (never truncates).

```python
context = (
    ContextWindowBuilder()
    .set_system_prompt(SYSTEM_PROMPT)       # ~500 tokens
    .add_chunks(reranked, max_tokens=4000)  # top-5 chunks
    .add_conversation(turns, max_tokens=600) # last 3 turns
    .add_query(query)                        # current query
    .build()
)
```

**8. OpenAILLM with Streaming**
GPT-4o for complex queries, GPT-4o-mini for simple (model routing).
Streaming enabled — first token within 500ms.
Grounding instruction: 'Answer ONLY using provided context.
If not in context, say I do not know.'
Citation format: [Source N] inline with source URL.

**9. Async Post-Processing (Observer Pattern)**
After response is streamed to user, three non-blocking tasks fire:
CacheWriteObserver → writes to Redis
TraceObserver → sends to LangSmith async
MetricsObserver → emits to Prometheus

**10. Circuit Breakers on All External Calls**
OpenAI: opens after 5 failures in 60s → return raw chunks
Qdrant: opens after 3 failures in 30s → BM25-only fallback
Cohere: opens after 3 failures in 30s → passthrough reranker
Redis: opens after 3 failures in 30s → bypass cache

**11. Prometheus Metrics**
Every pipeline stage tracked: latency histograms per stage,
token counts, cost per query, cache hit/miss, circuit breaker state.
Grafana dashboard: service health, quality metrics, cost per tenant.

### The Full Query Pipeline in Code (Wired Together)
```python
async def handle_query(query: str, tenant_id: str, session_id: str):
    # Gate 1: exact cache
    cached = await cache.get_exact(query, tenant_id)
    if cached: return cached

    # Parallel: embed + rewrite + fetch conversation history
    (dense, sparse), rewritten, turns = await asyncio.gather(
        embed_parallel(query),
        query_rewriter.rewrite(query, history=[]),
        conversation_repo.get_turns(session_id, limit=3),
        return_exceptions=True
    )

    # Hybrid search (parallel internally in Qdrant)
    candidates = await vectordb_breaker.call(
        qdrant.hybrid_search, dense, sparse, tenant_id, top_k=20,
        fallback=bm25_fallback
    )

    # Rerank (with fallback)
    top_chunks = await reranker_breaker.call(
        cohere.rerank, rewritten, candidates, top_n=5,
        fallback=passthrough_reranker.rerank
    )

    # Build context window (Builder pattern enforces token budget)
    context = (
        ContextWindowBuilder()
        .set_system_prompt(SYSTEM_PROMPT)
        .add_chunks(top_chunks, max_tokens=4000)
        .add_conversation(turns, max_tokens=600)
        .add_query(query)
        .build()
    )

    # Generate with circuit breaker
    response = await llm_breaker.call(
        openai.generate, context, stream=True,
        fallback=chunk_fallback
    )

    # Async post-processing (fire and forget)
    asyncio.create_task(
        notify_observers(query, response, top_chunks, tenant_id)
    )
    return response
```

### Quality Gate (RAGAS — Run First Time Here)
Create golden dataset: 50 question-answer pairs from indexed docs.
Run RAGAS evaluation. Record baseline numbers.
These become your CI gate thresholds.

Target minimums before Phase 3:
Faithfulness ≥ 0.80
Answer Relevancy ≥ 0.75
Context Precision ≥ 0.65
Context Recall ≥ 0.65
Latency p95 < 3s

If any metric below target: fix before proceeding.
Phase 3 is not started until Phase 2 passes quality gate.

### Exit Criteria
POST /query returns grounded, cited answers.
All circuit breakers tested (manually kill services, verify fallbacks).
RAGAS baseline established on 50-question golden set.
All metrics flowing to Prometheus. LangSmith traces visible.

### Phase 2 Sub-Phase: Retrieval Configuration Selection

Before finalizing the query pipeline configuration, we run an
empirical comparison on retrieval parameters.

**Parameters compared:**

Top-K before reranking:
  Candidate A: Retrieve top-10, rerank to top-5
  Candidate B: Retrieve top-20, rerank to top-5
  Candidate C: Retrieve top-30, rerank to top-5
  Hypothesis: top-20 hits the precision-recall sweet spot.
  Top-10 may miss relevant chunks (low recall).
  Top-30 adds noise without meaningful recall gain.

Hybrid search weight:
  Candidate A: Pure vector (dense only)
  Candidate B: Hybrid RRF (dense + sparse, equal weight)
  Candidate C: BM25-heavy hybrid (0.6 BM25, 0.4 vector)
  Hypothesis: hybrid RRF wins for general technical docs.
  BM25-heavy wins for queries with exact technical terms
  (error codes, API names, version numbers).

Reranker vs no reranker:
  Candidate A: Hybrid retrieval, no reranking
  Candidate B: Hybrid retrieval + Cohere reranker
  Hypothesis: reranker consistently wins on Precision@5.
  The 150ms latency cost is worth it.

**Measurement process:**

Same golden evaluation set from Phase 1 chunking comparison.
Now fixed on the winning chunking strategy — only retrieval varies.
Metrics: Precision@5, Recall@5, MRR, NDCG@5.
RAGAS Context Precision and Context Recall also run here
for the first time (these require the full pipeline).

**Expected output:**

Retrieval Configuration Comparison:
| Configuration           | P@5  | R@5  | MRR  | NDCG@5 | Latency p95 |
|-------------------------|------|------|------|--------|-------------|
| Vector only, top-5      | ?    | ?    | ?    | ?      | ?           |
| Hybrid RRF, top-10      | ?    | ?    | ?    | ?      | ?           |
| Hybrid RRF, top-20      | ?    | ?    | ?    | ?      | ?           |
| Hybrid + Cohere, top-20 | ?    | ?    | ?    | ?      | ?           |

Winner: [fill in after measurement]

---

## PHASE 3 — MCP SERVER + REMAINING CONNECTORS (Week 4)

### Entry Criteria
Phase 2 complete. Query pipeline passes quality gate.

### What Gets Built
MCP server exposing two tools to AI agents, remaining connectors
(GitHub, PDF, Slack), and PDF/Slack ingestion validation.

**1. MCP Server (separate process :8002)**
SSE transport for hosted MCP (works with Cursor, Claude Code).
Two tools:
1. search_knowledge_base(query: str, session_id: str)
    → delegates to internal HTTP POST /query
    → returns: answer + source citations + session_id
2. fetch_and_query_online_docs(url: str, query: str)
    → fetches URL content (requests + BeautifulSoup)
    → builds temporary in-memory index
    → runs same RAG pipeline
    → caches result in Redis for 30 minutes (TTL)
    → returns: answer + source URL

Why separate process: MCP uses SSE/stdio protocol, not HTTP.
Long-lived agent connections (entire coding session) behave
differently from short-lived HTTP requests. Independent failure
modes — MCP crash does not affect REST API users.

**2. GitHubConnector**
Fetches README.md, docs/, markdown files from a GitHub repo.
Handles code-aware chunking (preserve function/class boundaries).
Respects GitHub API rate limits with exponential backoff.

**3. PDFConnector**
Text-based PDFs: PyMuPDF direct extraction.
Scanned PDFs: detected by avg chars/page < 100 → OCR via Tesseract.
Table extraction: Camelot → convert to markdown before chunking.
Header/footer detection: strip repeating text at page top/bottom.

**4. SlackConnector**
Parses Slack JSON export format.
Filters system messages, bot messages.
Groups messages by thread for context-preserving chunks.

**5. GitHub Actions CI Pipeline**
RAGAS runs on every PR touching backend/, prompts/, or eval/.
Golden set: 100 question-answer pairs (expanded from Phase 2's 50).
CI fails if any RAGAS metric drops > 0.03 below baseline.
Thresholds ratchet up — locked in after every improvement.

### Quality Gate
MCP server connects to Cursor. Verify search_knowledge_base
returns grounded answers via the MCP tool interface.
RAGAS golden set expanded to 100 questions. CI gate active.

### Exit Criteria
MCP server works in Cursor and Claude Code.
All 4 connectors functional.
GitHub Actions CI running RAGAS on every PR.

---

## PHASE 4 — EVALUATION PIPELINE + PRODUCTION HARDENING (Week 5)

### Entry Criteria
Phase 3 complete. All connectors working. CI gate active.

### What Gets Built
Production-grade reliability, complete RAGAS evaluation pipeline,
and observability to match a system you would actually deploy.

**1. Full RAGAS Evaluation Pipeline**
Golden dataset: 100+ queries with ground truth answers.
Metrics tracked: Faithfulness, Answer Relevancy,
Context Precision, Context Recall.
Evaluation runs: after every prompt change, after every model
update, weekly on schedule even with no deployments.
Deployment blocked if Faithfulness < 0.85.
LangSmith stores every eval trace for debugging.

**2. Retrieval Metrics (Classical IR)**
Precision@5, Recall@5, MRR — computed on annotated chunk pool.
Pooling strategy: union of top-20 from vector, BM25, hybrid.
LLM-assisted annotation (Haiku grades 0-3 per chunk).
Human spot-check: 10% of labels, Cohen's Kappa target κ ≥ 0.60.
These metrics pinpoint whether retrieval or generation is failing.

**3. TRADEOFFS.md**
Documents every major decision with:
  - What we chose
  - What we rejected and why
  - What breaks if this decision is wrong
  - The trigger to revisit it

**4. Production Hardening**
Retry with exponential backoff + full jitter on all external calls.
Rate limiting per tenant (Redis atomic INCR, sliding window).
Per-tenant document limits enforced at ingestion (default: 10,000).
Ingestion job checkpointing (resume from last good chunk on failure).
Idempotent chunk writes (upsert by deterministic chunk ID).
Dead letter queue for failed ingestion jobs.

**5. Grafana Dashboards**
Service health dashboard: p50/p95/p99 latency per stage,
error rate, circuit breaker states, active requests per tenant.
Quality dashboard: RAGAS faithfulness trend, context precision,
retrieval confidence distribution.
Cost dashboard: LLM cost per query per tenant, cache hit rate,
projected monthly cost.

**6. Docker Compose Production Overrides**
docker-compose.prod.yml: resource limits per container,
health check configs, log rotation, restart policies.
Deployment: single EC2 t3.xlarge for v1, all services via
Docker Compose, identical to local dev environment.

### Quality Gate
RAGAS evaluation: Faithfulness ≥ 0.88, Context Precision ≥ 0.72.
Retrieval Precision@5 ≥ 0.68, MRR ≥ 0.72.
All circuit breaker fallbacks tested under load.
TRADEOFFS.md reviewed and complete.

### Exit Criteria
System ready to onboard first real tenant.
All dashboards showing real data.
TRADEOFFS.md published and linked from README.
Production EC2 deployment working.

### Phase 4 Sub-Phase: Generation Parameter Tuning

Before finalizing the generation configuration, we run RAGAS
comparisons on generation parameters.

**Parameters compared:**

LLM model selection:
  Candidate A: GPT-4o-mini for all queries
  Candidate B: GPT-4o for all queries
  Candidate C: GPT-4o-mini for simple, GPT-4o for complex (routing)
  Metric: Faithfulness, Answer Relevancy, cost per query, latency p95
  Hypothesis: routing wins — comparable quality to GPT-4o at ~40% cost.

Context window size (chunks passed to LLM):
  Candidate A: top-3 chunks (conservative, less noise)
  Candidate B: top-5 chunks (our current default)
  Candidate C: top-7 chunks (more context, more tokens)
  Metric: Faithfulness, Context Precision (higher context = more noise risk)
  Hypothesis: top-5 is the sweet spot. top-7 increases token cost
  with diminishing quality return. top-3 risks low recall for
  multi-part questions.

Grounding prompt variants:
  Variant A: 'Answer based only on the context provided.'
  Variant B: 'Answer ONLY using the provided context. If the answer
              is not in the context, say I do not know. Never add
              information not present in the context.'
  Variant C: Variant B + 'Cite the source chunk for every claim.'
  Metric: Faithfulness (primary), hallucination rate
  Hypothesis: Variant C wins on faithfulness — explicit citation
  instruction forces the model to stay grounded.

**Expected output:**

Generation Configuration Comparison:
| Configuration              | Faithfulness | Ctx Precision | Cost/query | Latency p95 |
|----------------------------|--------------|---------------|------------|-------------|
| GPT-4o-mini, top-5, var A  | ?            | ?             | ?          | ?           |
| GPT-4o, top-5, var A       | ?            | ?             | ?          | ?           |
| Routing, top-5, var C      | ?            | ?             | ?          | ?           |
| Routing, top-3, var C      | ?            | ?             | ?          | ?           |
| Routing, top-7, var C      | ?            | ?             | ?          | ?           |

Winner: [fill in after measurement]

---

## EVALUATION-DRIVEN DEVELOPMENT — THE RATCHET

This project follows one rule: thresholds only go up, never down.

After Phase 2 baseline: set CI gate = baseline - 0.03.
After Phase 4 hardening: raise CI gate = new score - 0.02.
After any improvement: raise CI gate to lock it in.

Ratchet targets:
Faithfulness: ≥ 0.90
Answer Relevancy: ≥ 0.85
Context Precision: ≥ 0.75
Context Recall: ≥ 0.78
Latency p95: < 2s
Cost per query: < $0.02

---

## WHAT BREAKS FIRST (BOTTLENECK ORDER AT EACH PHASE)

Phase 1: Qdrant RAM exhaustion on large docs sites.
  Fix: per-tenant document limit enforced at ingestion.

Phase 2: OpenAI rate limits on high query volume.
  Fix: model routing + caching + circuit breaker.

Phase 3: MCP SSE connection drops during long coding sessions.
  Fix: SSE heartbeat every 30s + graceful restart (SIGTERM drain).

Phase 4: RAGAS faithfulness below 0.85 on first real tenant.
  Fix: improve grounding prompt, ensure top-5 chunks are relevant.
       Check context precision first — if below 0.65, fix reranker.

---

## DESIGN PATTERNS — WHERE EACH ONE LIVES IN THE CODE

Pattern          | File                          | Purpose
-----------------|-------------------------------|---------------------------
Strategy         | strategies/base.py            | All provider interfaces
Factory          | connectors/factory.py         | ConnectorFactory routing
Repository       | repositories/base.py          | Data access abstraction
Circuit Breaker  | core/circuit_breaker.py       | Failure isolation
Observer         | observers/base.py             | Async post-processing
Builder          | core/context_builder.py       | Context window assembly




