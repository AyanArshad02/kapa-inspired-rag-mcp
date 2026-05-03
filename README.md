# kapa-inspired RAG MCP

> A production-grade, multi-tenant documentation RAG system with empirically validated retrieval, streaming answers, and an MCP server — built from first principles to match what real AI infrastructure companies ship.

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Qdrant](https://img.shields.io/badge/Qdrant-1.13-DC143C?style=flat)](https://qdrant.tech)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991?style=flat&logo=openai&logoColor=white)](https://openai.com)
[![Cohere](https://img.shields.io/badge/Cohere-Rerank_v3-orange?style=flat)](https://cohere.com)
[![RAGAS](https://img.shields.io/badge/RAGAS-All_Gates_Passed-brightgreen?style=flat)](https://docs.ragas.io)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat)](LICENSE)

---

## What This Is

Most RAG tutorials stop at "chunk → embed → retrieve → generate." This project goes further — it's what a real company like [kapa.ai](https://kapa.ai) actually has to build:

- **Multi-tenant isolation** — separate Qdrant collections per tenant, API key auth, per-tenant rate limiting
- **Empirically validated retrieval stack** — 12-combination chunker × retriever experiment on real docs + 78 Q&A frozen eval set
- **Streaming answers** — SSE token-by-token generation, conversation memory, Redis cache layer
- **MCP server** — tools exposed via the Model Context Protocol so Claude/Cursor can query the knowledge base directly
- **RAGAS-gated CI** — retrieval quality is a first-class contract, not an afterthought

---

## RAGAS Eval Results

Evaluated on **78 Q&A pairs** generated from real FastAPI + Supabase documentation.

| Metric            | Score           | Gate    | Status |
| ----------------- | --------------- | ------- | ------ |
| Faithfulness      | **0.908** | ≥ 0.85 | ✅     |
| Answer Relevancy  | **0.832** | ≥ 0.80 | ✅     |
| Context Precision | **0.892** | ≥ 0.85 | ✅     |
| Context Recall    | **0.949** | ≥ 0.90 | ✅     |

Pipeline: `HeadingAwareChunker → text-embedding-3-small → Qdrant top-20 → Cohere rerank-english-v3.0 → top-5 → GPT-4o`

See full experiment analysis in [experiments/](experiments/) and decision rationale in [TRADEOFFS.md](TRADEOFFS.md).

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Clients                               │
│         Claude / Cursor (MCP)  │  REST API consumers        │
└──────────────────┬──────────────┬───────────────────────────┘
                   │              │
          MCP SSE transport    FastAPI (auth middleware)
                   │              │
         ┌─────────▼──────────────▼──────────┐
         │        Layer A — Orchestrators     │
         │  QueryPipeline │ IngestionPipeline │
         └────────────────┬──────────────────┘
                          │
         ┌────────────────▼──────────────────────────────┐
         │        Layer B — Strategy Interfaces           │
         │  LLMStrategy │ EmbeddingStrategy │ VectorDB   │
         │  RerankerStrategy │ CacheStrategy │ Chunker   │
         └────────────────┬──────────────────────────────┘
                          │
         ┌────────────────▼──────────────────────────────┐
         │        Layer C — Implementations               │
         │                                               │
         │  OpenAILLM  (router: gpt-4o / gpt-4o-mini)   │
         │  OpenAIEmbedding  (text-embedding-3-small)    │
         │  TFSparseEncoder  (BM25 baseline)             │
         │  QdrantDB  (dense + hybrid RRF)               │
         │  CohereReranker  (rerank-english-v3.0)        │
         │  RedisCache  (JSON TTL)                       │
         │  HeadingAwareChunker │ SlidingWindowChunker   │
         └───────────────────────────────────────────────┘
                          │
         ┌────────────────▼──────────────────────────────┐
         │             Infrastructure                      │
         │   PostgreSQL │ Qdrant │ Redis │ Celery/SQS    │
         └───────────────────────────────────────────────┘
```

### 3-Layer Design

| Layer                          | What                                     | Why                                                 |
| ------------------------------ | ---------------------------------------- | --------------------------------------------------- |
| **A** — Orchestrators   | `QueryPipeline`, `IngestionPipeline` | Business logic lives here; no infra imports         |
| **B** — Interfaces      | `LLMStrategy`, `VectorDB`, etc.      | Swap implementations without touching orchestrators |
| **C** — Implementations | `OpenAILLM`, `QdrantDB`, etc.        | All infra and API calls isolated here               |

---

## Key Technical Decisions

Every decision below has benchmark numbers. Full analysis in [TRADEOFFS.md](TRADEOFFS.md).

### Why HeadingAwareChunker?

HAC and SlidingWindow-128 both hit **Recall@5 = 0.821**, but HAC gets **MRR 0.755 vs 0.687** — the right answer appears at rank 1 more often. HAC also produces 127 chunks vs 259 (50% fewer), making retrieval cheaper. Markdown docs have heading boundaries for a reason.

### Why Dense over Hybrid?

BM25 fails on paraphrased queries (`"how to add a task"` vs `.add_task()`). Once a reranker is present, Dense and Hybrid converge to identical scores — so Hybrid adds complexity with zero benefit.

### Why Cohere Reranker?

Single biggest quality lever: MRR jumps from **0.755 → 0.795** (+0.040) with Dense, and from **0.679 → 0.795** (+0.116) with Hybrid. The reranker rescues well-retrieved but poorly-ranked chunks. The system is now reranker-dominated — Cohere sets the final ranking, not retrieval order.

### Model Router

```
total_tokens ≤ 500  →  gpt-4o-mini   (fast, cheap)
total_tokens > 500  →  gpt-4o        (full context window)
```

---

## Project Structure

```
kapa-inspired-rag-mcp/
├── backend/
│   ├── api/
│   │   ├── ingestion_service.py        # POST /ingest, GET /ingest/{job_id}
│   │   ├── query_service.py            # POST /query (SSE + JSON), DELETE /conversation
│   │   └── middleware/auth.py          # API key → tenant_id
│   ├── core/
│   │   ├── ingestion_pipeline.py       # Layer A: ingestion orchestrator
│   │   ├── query_pipeline.py           # Layer A: query orchestrator
│   │   └── context_window_builder.py   # tiktoken, 6000 token budget, greedy fill
│   ├── strategies/
│   │   ├── base.py                     # Layer B: all abstract interfaces
│   │   ├── llm/openai_llm.py           # GPT-4o + model router + circuit breaker
│   │   ├── embedding/                  # OpenAI dense + TF sparse (BM25)
│   │   ├── vectordb/qdrant_db.py       # Dense + hybrid RRF, per-tenant collections
│   │   ├── reranker/                   # Cohere + Passthrough (no-op for tests)
│   │   └── cache/redis_cache.py        # JSON serialise/deserialise, TTL setex
│   ├── observers/
│   │   ├── cache_observer.py           # Writes result to Redis after response
│   │   ├── trace_observer.py           # LangSmith traces (optional)
│   │   └── metrics_observer.py         # Prometheus counters + histograms
│   ├── repositories/
│   │   ├── postgres_ingestion_job_repo.py
│   │   ├── postgres_conversation_repo.py   # Turn pairs, FK-safe inserts
│   │   └── postgres_tenant_repo.py
│   ├── connectors/                     # DocsConnector + (GitHub/PDF/Slack in Phase 3)
│   ├── mcp/                            # MCP server (Phase 3)
│   ├── models.py                       # Chunk, QueryResult, Turn, IngestionJob
│   └── config.py                       # pydantic-settings, fail-fast validation
├── experiments/
│   ├── 01_eval_set_generation.ipynb    # GPT-4o generated 78 Q&A pairs
│   ├── 02_docs_chunking_retrieval.ipynb # 12 chunker × retriever combinations
│   ├── 03_reranker_comparison.ipynb    # Dense/Hybrid × with/without Cohere
│   └── 04_ragas_baseline.ipynb         # RAGAS gate — all 4 metrics passed
├── eval/
│   └── golden_dataset/docs/eval_v1.jsonl  # 78 frozen Q&A pairs
├── tests/
│   ├── unit/                           # 33 unit tests (no infra needed)
│   └── integration/                    # 3 integration tests (real Qdrant + Postgres)
├── system-design/                      # 10-step system design docs
├── TRADEOFFS.md                        # Every decision + benchmark numbers
└── docker-compose.yml
```

---

## Retrieval Flow

```
Query
  │
  ├── Cache hit?  →  return immediately  (Redis, configurable TTL)
  │
  ├── Embed query  (text-embedding-3-small, 1536-dim)
  │
  ├── Retrieve top-20 from Qdrant  (dense ANN, per-tenant collection)
  │
  ├── Rerank with Cohere rerank-english-v3.0  →  top-5
  │
  ├── Build context window  (6000 token budget, greedy fill, tiktoken)
  │
  ├── Route to model  (gpt-4o-mini / gpt-4o based on context size)
  │
  └── Stream answer tokens via SSE  →  save Turn to Postgres
```

---

## Connectors

| Source                  | Chunker                   | Eval Status           |
| ----------------------- | ------------------------- | --------------------- |
| Docs sites (.md / .mdx) | `HeadingAwareChunker`   | Empirically validated |
| GitHub repos            | `CodeBlockAwareChunker` | Pending               |
| PDFs                    | `HierarchicalChunker`   | Pending               |
| Slack channels          | `ThreadAwareChunker`    | Pending               |

Each source type gets its own eval set and experiment before being shipped.

---

## Getting Started

### Prerequisites

- Python 3.11+
- Docker + Docker Compose
- OpenAI API key
- Cohere API key

### 1. Clone and install

```bash
git clone https://github.com/AyanArshad02/kapa-inspired-rag-mcp.git
cd kapa-inspired-rag-mcp
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
```

### 2. Set environment variables

```bash
cp .env.example .env
# Edit .env
# fill in OPENAI_API_KEY and COHERE_API_KEY
```

### 3. Start infrastructure

```bash
docker-compose up -d postgres qdrant redis
```

### 4. Run tests

```bash
# Unit tests — no infra needed
pytest tests/unit -v

# Integration tests — requires running docker-compose
pytest tests/integration -m integration -v
```

### 5. Start the API

```bash
uvicorn backend.api.query_service:app --reload --port 8001
```

### 6. Ingest a docs source

```bash
curl -X POST http://localhost:8000/ingest \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"source_url": "https://fastapi.tiangolo.com/tutorial/", "source_type": "docs_site"}'
```

### 7. Query (streaming)

```bash
curl -X POST http://localhost:8001/query \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"query": "How does dependency injection work in FastAPI?", "stream": true}'
```

### 7. Query (JSON)

```bash
curl -X POST http://localhost:8001/query \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"query": "How does dependency injection work in FastAPI?", "stream": false}'
```

---

## API Reference

### Ingestion Service

| Method   | Endpoint             | Description                                           |
| -------- | -------------------- | ----------------------------------------------------- |
| `POST` | `/ingest`          | Submit URL for ingestion — async, returns `job_id` |
| `GET`  | `/ingest/{job_id}` | Poll ingestion job status                             |

### Query Service

| Method     | Endpoint                     | Description                                                   |
| ---------- | ---------------------------- | ------------------------------------------------------------- |
| `POST`   | `/query`                   | Ask a question —`stream: true` for SSE, `false` for JSON |
| `DELETE` | `/query/conversation/{id}` | Clear conversation history                                    |
| `GET`    | `/health`                  | Health check                                                  |

### SSE Response Format

```
data: {"token": "Dependency"}
data: {"token": " injection"}
data: {"token": " in FastAPI allows..."}
data: [DONE]
```

---

## Observability

| Signal              | Implementation                                                                                                |
| ------------------- | ------------------------------------------------------------------------------------------------------------- |
| Query traces        | LangSmith — set `LANGSMITH_API_KEY` to enable, silently skips if absent                                    |
| Prometheus metrics  | `rag_queries_total` (counter), `rag_query_tokens` (histogram), `rag_source_chunks_returned` (histogram) |
| Ingestion job state | PostgreSQL `ingestion_jobs` table — status, checkpoint, error                                              |
| Circuit breaker     | Built into `OpenAILLM` and `OpenAIEmbedding` — fails fast, recovers automatically                        |

---

## Experiments

The retrieval stack was chosen empirically, not by convention.

| Notebook                       | What                                         | Result                  |
| ------------------------------ | -------------------------------------------- | ----------------------- |
| `01_eval_set_generation`     | GPT-4o generates 78 Q&A pairs from real docs | Frozen eval set created |
| `02_docs_chunking_retrieval` | 12 combinations: 4 chunkers × 3 retrievers  | HAC + Dense wins on MRR |
| `03_reranker_comparison`     | Dense/Hybrid × with/without Cohere          | Reranker: +0.040 MRR    |
| `04_ragas_baseline`          | Full pipeline RAGAS evaluation               | All 4 gates passed      |

The eval set (`eval/golden_dataset/docs/eval_v1.jsonl`) is **frozen**. Ground truth is tied to 40-character text anchors from source docs, not chunk IDs — it survives chunking changes.

---

## System Design

Full 10-step system design lives in [system-design/](system-design/):

`Clarifying Questions → Functional Requirements → NFRs → Capacity Planning → HLD → Database ADR → Architecture ADRs → Pre-mortem → Implementation Plan → Class + Sequence Diagrams`

This isn't boilerplate. The pre-mortem identified real failure modes (BM25 paraphrase failures, JSONB asyncpg bugs, UUID tenant isolation) that were all fixed before they became production issues.

---

## Roadmap

- [X] **Phase 0** — Scaffolding, interfaces, docker-compose
- [X] **Phase 1** — Ingestion pipeline (embed + upsert + job tracking)
- [X] **Phase 2** — Query pipeline (stream + cache + conversation + RAGAS baseline)
- [ ] **Phase 3** — MCP server, GitHub/PDF/Slack connectors, CI RAGAS gate
- [ ] **Phase 4** — Generation tuning, rate limiting, Prometheus dashboards
- [ ] **Phase 5** — Demo on Kubernetes docs, YouTube walkthrough
- [ ] **Phase 6** — AWS deployment (ECS Fargate, RDS, ElastiCache, ALB, blue/green)

---

## License

MIT — see [LICENSE](LICENSE).

---

## Author

Built by **Ayan Arshad** · [GitHub](https://github.com/AyanArshad02)

> This project reverse-engineers the architecture behind tools like [kapa.ai](https://kapa.ai), not as a competitor, but as a rigorous exercise in building production RAG systems that are actually evaluated, not just vibes-checked.
