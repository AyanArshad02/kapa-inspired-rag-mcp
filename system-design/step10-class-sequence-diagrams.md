# Step 10 — Class Diagrams, Sequence Diagrams & LLD

This is the Low-Level Design document. Every class, every interface,
every design pattern is defined here. Code structure is derived from this
document.

---

## SOLID PRINCIPLES — HOW THEY APPLY TO EVERY CLASS

Before the diagrams, here is how SOLID maps to this codebase.
Every class decision references these principles explicitly.

**Single Responsibility (SRP)**
Every class does exactly one thing.
QdrantDB stores and retrieves vectors — it does not rerank.
CohereReranker reranks — it does not embed.
ContextWindowBuilder builds context — it does not call the LLM.

**Open/Closed (OCP)**
New LLM providers, connectors, or chunkers are added by implementing
an interface and registering in a factory. Zero changes to the pipeline.
The pipeline is closed for modification, open for extension.

**Liskov Substitution (LSP)**
Any LLMStrategy implementation can replace any other.
The pipeline never knows if it is talking to GPT-4o or Claude.
All strategies are interchangeable at runtime.

**Interface Segregation (ISP)**
EmbeddingStrategy only has embed().
It does not have generate() or rerank().
Thin interfaces prevent classes from implementing methods they do not need.

**Dependency Inversion (DIP)**
The QueryPipeline depends on LLMStrategy, not OpenAILLM.
The IngestionPipeline depends on VectorDBStrategy, not QdrantDB.
High-level modules depend on abstractions, not concrete implementations.

---

## PART 1 — CLASS DIAGRAMS

### 1.1 Strategy Interfaces (base.py)

All strategy interfaces live in one file. This is the contract
the entire system is built on. If this file is wrong, everything
downstream is wrong. Define it once, never change the interface.

```
┌─────────────────────────────────┐
│        <<interface>>            │
│        LLMStrategy              │
├─────────────────────────────────┤
│ + generate(                     │
│     messages: list[dict],       │
│     stream: bool = False        │
│   ) -> AsyncGenerator | dict    │
└─────────────────────────────────┘
         ▲              ▲
         │              │
┌────────────────┐  ┌────────────────┐
│   OpenAILLM    │  │   ClaudeLLM    │
├────────────────┤  ├────────────────┤
│ - client       │  │ - client       │
│ - model_id     │  │ - model_id     │
│ - model_router │  └────────────────┘
└────────────────┘
(routes GPT-4o-mini vs GPT-4o
 based on query complexity)


┌─────────────────────────────────┐
│        <<interface>>            │
│       EmbeddingStrategy         │
├─────────────────────────────────┤
│ + embed(                        │
│     texts: list[str]            │
│   ) -> list[list[float]]        │
└─────────────────────────────────┘
         ▲              ▲
         │              │
┌──────────────────┐  ┌──────────────────┐
│ OpenAIEmbedding  │  │  LocalEmbedding  │
├──────────────────┤  ├──────────────────┤
│ - client         │  │ - model          │
│ - model_id       │  │ (all-MiniLM,     │
│ - cache: Redis   │  │  fallback only)  │
└──────────────────┘  └──────────────────┘


┌─────────────────────────────────────────┐
│           <<interface>>                 │
│           VectorDBStrategy              │
├─────────────────────────────────────────┤
│ + upsert(                               │
│     chunks: list[Chunk],                │
│     tenant_id: str                      │
│   ) -> None                             │
│ + hybrid_search(                        │
│     dense_vec: list[float],             │
│     sparse_vec: SparseVector,           │
│     tenant_id: str,                     │
│     top_k: int                          │
│   ) -> list[Chunk]                      │
│ + delete_chunks(                        │
│     doc_id: str,                        │
│     tenant_id: str                      │
│   ) -> None                             │
└─────────────────────────────────────────┘
         ▲                    ▲
         │                    │
┌─────────────────┐  ┌─────────────────┐
│    QdrantDB     │  │   PineconeDB    │
├─────────────────┤  ├─────────────────┤
│ - client        │  │ - index         │
│ - collection_   │  │ - namespace_    │
│   prefix        │  │   prefix        │
└─────────────────┘  └─────────────────┘
(self-hosted,         (managed, swap in
 zero extra cost)      via config only)


┌─────────────────────────────────────────┐
│           <<interface>>                 │
│          RerankerStrategy               │
├─────────────────────────────────────────┤
│ + rerank(                               │
│     query: str,                         │
│     chunks: list[Chunk],                │
│     top_n: int                          │
│   ) -> list[Chunk]                      │
└─────────────────────────────────────────┘
         ▲                    ▲
         │                    │
┌──────────────────┐  ┌────────────────────────┐
│ CohereReranker   │  │ PassthroughReranker    │
├──────────────────┤  ├────────────────────────┤
│ - client         │  │ (returns top_n by      │
│ - model_id       │  │  retrieval score only, │
└──────────────────┘  │  no API call —         │
                      │  circuit breaker       │
                      │  fallback)             │
                      └────────────────────────┘


┌─────────────────────────────────────────┐
│           <<interface>>                 │
│          ConnectorStrategy              │
├─────────────────────────────────────────┤
│ + can_handle(source_type: str) -> bool  │
│ + fetch(                                │
│     source_url: str,                    │
│     metadata: dict                      │
│   ) -> list[RawDocument]               │
└─────────────────────────────────────────┘
    ▲          ▲          ▲          ▲
    │          │          │          │
┌───────┐ ┌───────┐ ┌───────┐ ┌───────────┐
│ Docs  │ │GitHub │ │  PDF  │ │  Slack    │
│Conn.  │ │Conn.  │ │Conn.  │ │Connector  │
├───────┤ ├───────┤ ├───────┤ ├───────────┤
│chunker│ │chunker│ │chunker│ │chunker    │
│=Hdng  │ │=Code  │ │=Hier- │ │=Thread    │
│Aware  │ │Block  │ │archic.│ │Aware      │
└───────┘ └───────┘ └───────┘ └───────────┘
(Each connector owns its own chunker —
 chosen empirically in Phase 1)


┌─────────────────────────────────────────┐
│           <<interface>>                 │
│          ChunkerStrategy                │
├─────────────────────────────────────────┤
│ + chunk(                                │
│     text: str,                          │
│     metadata: dict                      │
│   ) -> list[Chunk]                      │
└─────────────────────────────────────────┘
    ▲           ▲           ▲           ▲
    │           │           │           │
┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
│ Heading  │ │Sliding   │ │Hierarch- │ │Thread    │
│ Aware    │ │Window    │ │ical      │ │Aware     │
│ Chunker  │ │Chunker   │ │Chunker   │ │Chunker   │
└──────────┘ └──────────┘ └──────────┘ └──────────┘


┌─────────────────────────────────────────┐
│           <<interface>>                 │
│           QueueStrategy                 │
├─────────────────────────────────────────┤
│ + enqueue(job: IngestionJob) -> str     │
│ + dequeue() -> IngestionJob             │
│ + ack(job_id: str) -> None              │
└─────────────────────────────────────────┘
         ▲                    ▲
         │                    │
┌──────────────────┐  ┌──────────────┐
│ CeleryRedisQueue │  │   SQSQueue   │
├──────────────────┤  ├──────────────┤
│ - redis_url      │  │ - queue_url  │
│ - app: Celery    │  │ - client     │
└──────────────────┘  └──────────────┘
(default — already     (production swap
 in stack)              via config)
```

---

### 1.2 Repository Interfaces (repositories/base.py)

Repository pattern abstracts all data access. The pipeline
never writes SQL directly — it calls repository methods.
Swapping PostgreSQL for DynamoDB on conversation_turns
(at scale) requires implementing ConversationRepository,
not changing the pipeline.

```
┌─────────────────────────────────────────┐
│           <<interface>>                 │
│        ConversationRepository           │
├─────────────────────────────────────────┤
│ + get_turns(                            │
│     session_id: str,                    │
│     limit: int = 3                      │
│   ) -> list[Turn]                       │
│ + save_turn(                            │
│     session_id: str,                    │
│     turn: Turn                          │
│   ) -> None                             │
│ + expire_session(                       │
│     session_id: str                     │
│   ) -> None                             │
└─────────────────────────────────────────┘
              ▲
              │
┌─────────────────────────────────────────┐
│      PostgresConversationRepository     │
├─────────────────────────────────────────┤
│ - pool: asyncpg.Pool                    │
│ - rls_context: str (tenant_id)         │
└─────────────────────────────────────────┘
(swap to DynamoConversationRepository
 at 1M+ queries/day — zero pipeline change)


┌─────────────────────────────────────────┐
│           <<interface>>                 │
│         IngestionJobRepository          │
├─────────────────────────────────────────┤
│ + create_job(job: IngestionJob) -> str  │
│ + update_status(                        │
│     job_id: str,                        │
│     status: str,                        │
│     **kwargs                            │
│   ) -> None                             │
│ + get_job(job_id: str) -> IngestionJob  │
└─────────────────────────────────────────┘
              ▲
              │
┌─────────────────────────────────────────┐
│    PostgresIngestionJobRepository       │
├─────────────────────────────────────────┤
│ - pool: asyncpg.Pool                    │
└─────────────────────────────────────────┘
```

---

### 1.3 Core Domain Models (models.py)

These are the data structures that flow through the entire
system. Defined once, used everywhere.

```
┌─────────────────────────────────┐
│            Chunk                │
├─────────────────────────────────┤
│ + chunk_id: str                 │  # sha256(tenant_id + url + idx)
│ + doc_id: str                   │
│ + tenant_id: str                │
│ + content: str                  │  # original text (shown to user)
│ + dense_vector: list[float]     │  # 1536-dim
│ + sparse_vector: SparseVector   │  # SPLADE format
│ + source_url: str               │
│ + document_title: str           │
│ + chunk_index: int              │
│ + source_type: str              │  # docs|github|pdf|slack
│ + timestamp: datetime           │
│ + doc_version: str              │
│ + rerank_score: float | None    │  # set after reranking
└─────────────────────────────────┘

┌─────────────────────────────────┐
│            Turn                 │
├─────────────────────────────────┤
│ + session_id: str               │
│ + tenant_id: str                │
│ + role: str                     │  # user | assistant
│ + content: str                  │
│ + tokens: int                   │
│ + created_at: datetime          │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│         IngestionJob            │
├─────────────────────────────────┤
│ + job_id: str                   │
│ + tenant_id: str                │
│ + source_url: str               │
│ + source_type: str              │
│ + status: str                   │  # pending|running|completed|failed
│ + docs_processed: int           │
│ + docs_failed: int              │
│ + error_message: str | None     │
│ + checkpoint_url: str | None    │  # resume from last good doc
│ + created_at: datetime          │
│ + completed_at: datetime | None │
└─────────────────────────────────┘

┌─────────────────────────────────┐
│         ContextWindow           │
├─────────────────────────────────┤
│ + system_prompt: str            │
│ + chunks: list[Chunk]           │
│ + conversation: list[Turn]      │
│ + query: str                    │
│ + total_tokens: int             │
│ + messages() -> list[dict]      │  # formatted for LLM API
└─────────────────────────────────┘
```

---

### 1.4 Query Pipeline Classes

```
┌────────────────────────────────────────────────┐
│               QueryPipeline                    │
├────────────────────────────────────────────────┤
│ - llm: LLMStrategy                             │
│ - embedding: EmbeddingStrategy                 │
│ - vectordb: VectorDBStrategy                   │
│ - reranker: RerankerStrategy                   │
│ - cache: RedisCache                            │
│ - conversation_repo: ConversationRepository    │
│ - circuit_breakers: dict[str, CircuitBreaker]  │
│ - observers: list[QueryObserver]               │
│ - context_builder: ContextWindowBuilder        │
├────────────────────────────────────────────────┤
│ + handle(                                      │
│     query: str,                                │
│     tenant_id: str,                            │
│     session_id: str                            │
│   ) -> AsyncGenerator[str, None]               │
│ - _check_cache(query, tenant_id) -> dict|None  │
│ - _embed_parallel(query) -> tuple              │
│ - _retrieve(dense, sparse, tenant_id) -> list  │
│ - _rerank(query, chunks) -> list               │
│ - _build_context(chunks, turns, query) -> CW   │
│ - _generate(context) -> AsyncGenerator         │
│ - _post_process(query, response, chunks) -> None│
└────────────────────────────────────────────────┘
(depends on all strategies via DI — never on
 concrete implementations directly)


┌────────────────────────────────────────────────┐
│            ContextWindowBuilder                │
│            (Builder Pattern)                   │
├────────────────────────────────────────────────┤
│ - system_prompt: str | None                    │
│ - chunks: list[Chunk]                          │
│ - conversation: list[Turn]                     │
│ - query: str | None                            │
│ - max_tokens: int = 6000                       │
├────────────────────────────────────────────────┤
│ + set_system_prompt(prompt: str) -> Self       │
│ + add_chunks(                                  │
│     chunks: list[Chunk],                       │
│     max_tokens: int = 4000                     │
│   ) -> Self                                    │
│ + add_conversation(                            │
│     turns: list[Turn],                         │
│     max_tokens: int = 600                      │
│   ) -> Self                                    │
│ + add_query(query: str) -> Self                │
│ + build() -> ContextWindow                     │
│   (validates token budget via tiktoken,        │
│    drops lowest-ranked chunks if over limit,   │
│    never truncates mid-chunk)                  │
└────────────────────────────────────────────────┘


┌────────────────────────────────────────────────┐
│              CircuitBreaker                    │
├────────────────────────────────────────────────┤
│ - name: str                                    │
│ - state: CircuitState (CLOSED|OPEN|HALF_OPEN)  │
│ - failure_count: int                           │
│ - failure_threshold: int = 5                   │
│ - recovery_timeout: float = 30.0               │
│ - last_failure_time: float                     │
├────────────────────────────────────────────────┤
│ + call(                                        │
│     func: Callable,                            │
│     *args,                                     │
│     fallback: Callable | None,                 │
│     **kwargs                                   │
│   ) -> Any                                     │
│ - _on_success() -> None                        │
│ - _on_failure() -> None                        │
│ - _should_allow() -> bool                      │
└────────────────────────────────────────────────┘


┌────────────────────────────────────────────────┐
│           <<interface>> QueryObserver          │
│           (Observer Pattern)                   │
├────────────────────────────────────────────────┤
│ + notify(                                      │
│     query: str,                                │
│     response: str,                             │
│     chunks: list[Chunk],                       │
│     metadata: dict                             │
│   ) -> None                                    │
└────────────────────────────────────────────────┘
    ▲                ▲                ▲
    │                │                │
┌──────────┐  ┌──────────────┐  ┌───────────────┐
│  Cache   │  │    Trace     │  │   Metrics     │
│ Observer │  │   Observer   │  │   Observer    │
├──────────┤  ├──────────────┤  ├───────────────┤
│- redis   │  │- langsmith   │  │- prometheus   │
│  client  │  │  client      │  │  counters     │
│- ttl     │  │              │  │  histograms   │
└──────────┘  └──────────────┘  └───────────────┘
```

---

### 1.5 Ingestion Pipeline Classes

```
┌────────────────────────────────────────────────┐
│             IngestionPipeline                  │
├────────────────────────────────────────────────┤
│ - connector_factory: ConnectorFactory          │
│ - embedding: EmbeddingStrategy                 │
│ - splade: SPLADEEncoder                        │
│ - vectordb: VectorDBStrategy                   │
│ - queue: QueueStrategy                         │
│ - job_repo: IngestionJobRepository             │
├────────────────────────────────────────────────┤
│ + submit(                                      │
│     source_url: str,                           │
│     source_type: str,                          │
│     tenant_id: str                             │
│   ) -> str (job_id)                            │
│ + process_job(job: IngestionJob) -> None       │
│   (runs inside Celery worker)                  │
│ - _fetch(job) -> list[RawDocument]             │
│ - _chunk(docs, connector) -> list[Chunk]       │
│ - _embed_batch(chunks) -> list[Chunk]          │
│ - _encode_sparse(chunks) -> list[Chunk]        │
│ - _upsert(chunks, tenant_id) -> None           │
│ - _backup_s3(docs, tenant_id) -> None          │
└────────────────────────────────────────────────┘


┌────────────────────────────────────────────────┐
│              ConnectorFactory                  │
│              (Factory Pattern)                 │
├────────────────────────────────────────────────┤
│ - _connectors: list[ConnectorStrategy]         │
├────────────────────────────────────────────────┤
│ + get_connector(                               │
│     source_type: str                           │
│   ) -> ConnectorStrategy                       │
│ + register(                                    │
│     connector: ConnectorStrategy               │
│   ) -> None                                    │
└────────────────────────────────────────────────┘
(Adding new connector: implement ConnectorStrategy,
 call factory.register(NewConnector()).
 Zero pipeline changes. Open/Closed Principle.)


┌────────────────────────────────────────────────┐
│              FreshnessManager                  │
├────────────────────────────────────────────────┤
│ - vectordb: VectorDBStrategy                   │
│ - queue: QueueStrategy                         │
├────────────────────────────────────────────────┤
│ + run_incremental(tenant_id: str) -> None      │
│   (daily — only changed/new docs)              │
│ + run_full_reindex(tenant_id: str) -> None     │
│   (weekly — full rebuild, handles deletions)   │
│ - _detect_changes(                             │
│     current_urls: set[str],                    │
│     indexed_urls: set[str]                     │
│   ) -> tuple[set, set]  # (new, deleted)       │
└────────────────────────────────────────────────┘
(Scheduled via Celery Beat.
 Full re-index solves the ghost content problem —
 documents deleted from source but still in Qdrant.)
```

---

### 1.6 MCP Server Classes

```
┌────────────────────────────────────────────────┐
│                MCPServer                       │
├────────────────────────────────────────────────┤
│ - query_service_url: str                       │
│ - http_client: aiohttp.ClientSession           │
│ - tools: list[MCPTool]                         │
├────────────────────────────────────────────────┤
│ + start(transport: SSETransport) -> None       │
│ + handle_tool_call(                            │
│     tool_name: str,                            │
│     arguments: dict                            │
│   ) -> MCPToolResult                           │
└────────────────────────────────────────────────┘
(Thin protocol translation layer.
 Zero RAG logic lives here.
 All pipeline logic stays in query_service.)


┌────────────────────────────────────────────────┐
│          SearchKnowledgeBaseTool               │
├────────────────────────────────────────────────┤
│ + name: str = "search_knowledge_base"          │
│ + description: str                             │
│ + parameters: dict (JSON Schema)               │
├────────────────────────────────────────────────┤
│ + execute(                                     │
│     query: str,                                │
│     session_id: str,                           │
│     tenant_id: str                             │
│   ) -> MCPToolResult                           │
│   (delegates to HTTP POST /query)              │
└────────────────────────────────────────────────┘


┌────────────────────────────────────────────────┐
│         FetchAndQueryOnlineDocsTool            │
├────────────────────────────────────────────────┤
│ + name: str = "fetch_and_query_online_docs"    │
│ + description: str                             │
├────────────────────────────────────────────────┤
│ + execute(                                     │
│     url: str,                                  │
│     query: str                                 │
│   ) -> MCPToolResult                           │
│   (fetches URL → in-memory index →             │
│    same RAG pipeline → cache 30min in Redis)   │
└────────────────────────────────────────────────┘
```

---

## PART 2 — SEQUENCE DIAGRAMS

### 2.1 Query Pipeline — Happy Path (Cache Miss)

This is the most important flow in the system. Every millisecond
in this sequence is accounted for in the latency budget.

```
Agent/User    QueryService    Redis    Qdrant   Cohere    OpenAI   PostgreSQL
    │               │           │        │         │         │          │
    │ POST /query   │           │        │         │         │          │
    │──────────────►│           │        │         │         │          │
    │               │           │        │         │         │          │
    │               │ GET cache │        │         │         │          │
    │               │──────────►│        │         │         │          │
    │               │ MISS      │        │         │         │          │
    │               │◄──────────│        │         │         │          │
    │               │           │        │         │         │          │
    │               │ asyncio.gather (parallel)     │         │          │
    │               │─────────────────────────────►│  embed  │          │
    │               │  embed dense (~100ms)         │         │          │
    │               │  encode sparse (FastSPLADE)   │         │          │
    │               │  get_turns(session_id) ─────────────────────────►│
    │               │           │        │         │         │     turns│
    │               │◄────────────────────────────────────────────────-│
    │               │◄─────────────────────────────│  vecs   │          │
    │               │           │        │         │         │          │
    │               │ hybrid_search(dense+sparse)   │         │          │
    │               │───────────────────►│          │         │          │
    │               │  (dense+sparse     │          │         │          │
    │               │   parallel inside  │          │         │          │
    │               │   Qdrant, RRF      │          │         │          │
    │               │   built-in)        │          │         │          │
    │               │  top-20 chunks    │          │         │          │
    │               │◄──────────────────│          │         │          │
    │               │           │        │         │         │          │
    │               │ rerank(query, top-20)         │         │          │
    │               │──────────────────────────────►│         │          │
    │               │  top-5 chunks                │         │          │
    │               │◄─────────────────────────────│         │          │
    │               │           │        │         │         │          │
    │               │ ContextWindowBuilder.build()  │         │          │
    │               │  (system_prompt + chunks      │         │          │
    │               │   + turns + query,            │         │          │
    │               │   tiktoken check)             │         │          │
    │               │           │        │         │         │          │
    │               │ generate(context, stream=True)│         │          │
    │               │─────────────────────────────────────────►│         │
    │  stream tokens│           │        │         │         │  tokens  │
    │◄──────────────│◄───────────────────────────────────────-│         │
    │  (first token │           │        │         │         │          │
    │   < 500ms)    │           │        │         │         │          │
    │               │           │        │         │         │          │
    │               │ asyncio.create_task (fire and forget)   │          │
    │               │  ├── cache.set(query, response)         │          │
    │               │  ├── langsmith.log(full_trace)          │          │
    │               │  └── prometheus.emit(metrics)           │          │
    │               │   (Observer pattern — non-blocking)     │          │
    │               │           │        │         │         │          │

Total latency budget:
  Cache check:          ~2ms
  Parallel embed+turns: ~100ms (limited by embedding, not turns)
  Qdrant hybrid search: ~200ms (dense+sparse parallel internally)
  Cohere reranker:      ~200ms
  Context build:        ~10ms
  LLM generation:       ~800ms-1500ms (streaming)
  First token to user:  ~500ms
  p50 total:            ~500ms
  p95 total:            ~2s
```

---

### 2.2 Query Pipeline — Cache Hit (Early Exit)

```
Agent/User    QueryService    Redis
    │               │           │
    │ POST /query   │           │
    │──────────────►│           │
    │               │ GET cache │
    │               │──────────►│
    │               │   HIT     │
    │               │◄──────────│
    │  response     │           │
    │◄──────────────│           │
    │  (2ms total)  │           │

Cost:    ~$0.00001 (one Redis GET)
Latency: ~2ms
vs full: ~$0.018, ~1000ms
At 30% hit rate on 100K queries/day:
  Saves 30,000 × $0.018 = $540/day
```

---

### 2.3 Query Pipeline — Circuit Breaker Open (LLM Fallback)

```
Agent/User    QueryService    Qdrant   Cohere    OpenAI (DOWN)
    │               │           │         │            │
    │ POST /query   │           │         │            │
    │──────────────►│           │         │            │
    │               │ [cache miss, embed, retrieve, rerank...]
    │               │           │         │            │
    │               │ generate(context)               │
    │               │─────────────────────────────────►│
    │               │         TIMEOUT / ERROR          │
    │               │◄─────────────────────────────────│
    │               │ CircuitBreaker._on_failure()     │
    │               │ (5th failure → state = OPEN)     │
    │               │           │         │            │
    │               │ fallback: return raw top-5 chunks│
    │               │  with message:                   │
    │               │  "LLM temporarily unavailable.   │
    │               │   Here are the most relevant     │
    │               │   docs I found:"                 │
    │  degraded     │           │         │            │
    │  response     │           │         │            │
    │◄──────────────│           │         │            │
    │               │           │         │            │
    │               │ [30s later: state = HALF_OPEN]   │
    │               │ [next request: one test call]    │
    │               │ [success: state = CLOSED]        │

System never returns a blank error.
Users get degraded but functional response.
This is what separates production from demo.
```

---

### 2.4 Ingestion Pipeline — Full Flow

```
TenantAdmin  IngestionSvc  Redis(Queue)  CeleryWorker  ConnFactory  Qdrant   S3   PostgreSQL
    │              │              │             │             │          │       │       │
    │ POST /ingest │              │             │             │          │       │       │
    │─────────────►│              │             │             │          │       │       │
    │              │ create_job() │             │             │          │       │       │
    │              │───────────────────────────────────────────────────────────────────►│
    │              │ job created  │             │             │          │       │       │
    │              │◄───────────────────────────────────────────────────────────────────│
    │              │ enqueue(job) │             │             │          │       │       │
    │              │─────────────►│             │             │          │       │       │
    │ 202 Accepted │              │             │             │          │       │       │
    │◄─────────────│              │             │             │          │       │       │
    │ {job_id}     │              │             │             │          │       │       │
    │              │              │ dequeue()   │             │          │       │       │
    │              │              │────────────►│             │          │       │       │
    │              │              │             │ update_status(running) │       │       │
    │              │              │             │───────────────────────────────────────►│
    │              │              │             │ get_connector(type)   │       │       │
    │              │              │             │────────────►│          │       │       │
    │              │              │             │  connector  │          │       │       │
    │              │              │             │◄────────────│          │       │       │
    │              │              │             │ connector.fetch(url)   │       │       │
    │              │              │             │ connector.chunk(docs)  │       │       │
    │              │              │             │ (each connector uses   │       │       │
    │              │              │             │  its own ChunkerStrat) │       │       │
    │              │              │             │ embed_batch(chunks)    │       │       │
    │              │              │             │ encode_sparse(chunks)  │       │       │
    │              │              │             │ (parallel for each batch)       │       │
    │              │              │             │ upsert(chunks, tenant_id)       │       │
    │              │              │             │──────────────────────────────►│       │
    │              │              │             │ backup(raw_docs, tenant_id)    │       │
    │              │              │             │────────────────────────────────────►│ │
    │              │              │             │ update_status(completed)        │       │
    │              │              │             │───────────────────────────────────────►│
    │              │              │             │ ack(job_id)  │          │       │       │
    │              │              │◄────────────│             │          │       │       │

Idempotency: chunk_id = sha256(tenant_id + source_url + chunk_index)
Upsert not insert → re-running the same job is safe.
Checkpointing: job stores checkpoint_url → on failure, resumes
from last successfully processed document, not from start.
```

---

### 2.5 MCP Tool Call Flow (from Cursor)

```
Cursor/Claude  MCPServer(:8002)   QueryService(:8000)   [full pipeline]
    │                │                    │                    │
    │ MCP tool call  │                    │                    │
    │ search_knowledge_base(query, sid)   │                    │
    │───────────────►│                    │                    │
    │                │ translate to HTTP  │                    │
    │                │ POST /query        │                    │
    │                │───────────────────►│                    │
    │                │                    │  [full query       │
    │                │                    │   pipeline runs]   │
    │                │                    │───────────────────►│
    │                │                    │◄───────────────────│
    │                │   response JSON    │                    │
    │                │◄───────────────────│                    │
    │                │ format as MCP tool │                    │
    │                │ result             │                    │
    │  MCPToolResult │                    │                    │
    │◄───────────────│                    │                    │
    │ {answer,       │                    │                    │
    │  sources,      │                    │                    │
    │  citations}    │                    │                    │

MCP server is a protocol adapter, not a pipeline.
All business logic stays in query_service.
If query_service is down, MCP returns a clean tool error.
If MCP server is down, REST API users are unaffected.
Independent failure modes — this is the point of separation.
```

---

## PART 3 — DESIGN PATTERN LOCATION MAP

Where every pattern lives in the codebase. A senior engineer
reviewing the repo should be able to find any pattern in under
30 seconds.

```
Pattern          Location                        Why Here
─────────────────────────────────────────────────────────────────
Strategy         strategies/base.py              All interfaces in one file
                 strategies/llm/openai_llm.py    One file per implementation
                 strategies/embedding/...
                 strategies/vectordb/...
                 strategies/reranker/...

Factory          connectors/factory.py           Connector routing only
                 (ChunkerStrategy selected        Chunker selection is part
                  inside each Connector)          of connector init, not factory

Repository       repositories/base.py            Interface definitions
                 repositories/conversation_repo.py
                 repositories/ingestion_job_repo.py

Circuit Breaker  core/circuit_breaker.py         One class, many instances
                 (one instance per external dep:  Instantiated in QueryPipeline
                  OpenAI, Qdrant, Cohere, Redis)  and IngestionPipeline init

Observer         observers/base.py               QueryObserver interface
                 observers/cache_observer.py
                 observers/trace_observer.py
                 observers/metrics_observer.py
                 (fired via asyncio.create_task   Non-blocking by design
                  after response is streamed)

Builder          core/context_builder.py         ContextWindowBuilder only
                 (enforces token budget,          Called in QueryPipeline
                  ordering, tiktoken check)       at context assembly step

Dependency       All pipelines receive            Enables unit testing with
Injection        strategies via __init__          mocked strategies — no
                 (no hardcoded providers)         real API calls in tests
```

---

## PART 4 — EVALUATION CLASS DIAGRAM

```
┌────────────────────────────────────────────────┐
│              RAGASEvaluator                    │
├────────────────────────────────────────────────┤
│ - golden_dataset: list[EvalSample]             │
│ - metrics: list[RAGASMetric]                   │
│ - thresholds: dict[str, float]                 │
├────────────────────────────────────────────────┤
│ + run(rag_pipeline: QueryPipeline) -> Report   │
│ + check_gates(report: Report) -> bool          │
│   (returns False if any metric below           │
│    threshold — blocks CI deployment)           │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│               EvalSample                      │
├────────────────────────────────────────────────┤
│ + question: str                                │
│ + ground_truth: str                            │
│ + answer: str | None      # filled at runtime │
│ + contexts: list[str] | None  # filled at RT  │
└────────────────────────────────────────────────┘

┌────────────────────────────────────────────────┐
│           ClassicalIREvaluator                 │
├────────────────────────────────────────────────┤
│ - annotated_dataset: list[AnnotatedSample]     │
├────────────────────────────────────────────────┤
│ + precision_at_k(k: int) -> float              │
│ + recall_at_k(k: int) -> float                 │
│ + mrr(k: int = 10) -> float                    │
│ + ndcg_at_k(k: int) -> float                   │
│ + compare_chunking_strategies(                 │
│     strategies: list[ChunkerStrategy],         │
│     source_type: str                           │
│   ) -> ComparisonTable                         │
│   (Phase 1 empirical decision)                 │
│ + compare_retrieval_configs(                   │
│     configs: list[RetrievalConfig]             │
│   ) -> ComparisonTable                         │
│   (Phase 2 empirical decision)                 │
└────────────────────────────────────────────────┘

Quality Gate Thresholds (CI blocks if below):
  Faithfulness:      ≥ 0.85 (Phase 2) → ≥ 0.90 (Phase 4)
  Answer Relevancy:  ≥ 0.78 (Phase 2) → ≥ 0.85 (Phase 4)
  Context Precision: ≥ 0.65 (Phase 2) → ≥ 0.75 (Phase 4)
  Context Recall:    ≥ 0.65 (Phase 2) → ≥ 0.78 (Phase 4)
  Precision@5:       ≥ 0.60 (Phase 1) → ≥ 0.68 (Phase 4)
  MRR:               ≥ 0.65 (Phase 1) → ≥ 0.72 (Phase 4)

Thresholds ratchet up. They never go down.
```

---

## PART 5 — WHAT GETS TESTED AND HOW

Unit tests use dependency injection to mock every strategy.
No real API calls in unit tests. Tests run in milliseconds.

```python
# Example: testing QueryPipeline with mocked strategies
def test_query_returns_grounded_answer():
    pipeline = QueryPipeline(
        llm=MockLLM(response="The refund policy is 30 days."),
        embedding=MockEmbedding(vector=[0.1] * 1536),
        vectordb=MockVectorDB(chunks=[mock_chunk]),
        reranker=MockReranker(),
        cache=MockCache(hit=False),
        conversation_repo=MockConversationRepo(),
        circuit_breakers={},
        observers=[],
        context_builder=ContextWindowBuilder(),
    )
    result = asyncio.run(pipeline.handle("refund policy?", "t1", "s1"))
    assert "30 days" in result

# This works because QueryPipeline depends on
# LLMStrategy (interface), not OpenAILLM (concrete).
# Dependency Inversion Principle in action.
```

Integration tests hit real Qdrant and PostgreSQL running
in Docker Compose. No real OpenAI or Cohere calls —
those are mocked even in integration tests to avoid cost.

End-to-end tests (run before production deployment only)
use real APIs with a small fixed query set.
RAGAS CI gate runs here.







