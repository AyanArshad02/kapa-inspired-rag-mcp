# kapa-inspired RAG MCP

> A production-grade, multi-tenant documentation RAG system with empirically validated retrieval, JWT auth, streaming answers, chat history, and an MCP server

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Next.js-14-black?style=flat&logo=next.js&logoColor=white)](https://nextjs.org)
[![Qdrant](https://img.shields.io/badge/Qdrant-1.13-DC143C?style=flat)](https://qdrant.tech)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o-412991?style=flat&logo=openai&logoColor=white)](https://openai.com)
[![Cohere](https://img.shields.io/badge/Cohere-Rerank_v3-orange?style=flat)](https://cohere.com)
[![RAGAS](https://img.shields.io/badge/RAGAS-All_Gates_Passed-brightgreen?style=flat)](https://docs.ragas.io)
[![Docker](https://img.shields.io/badge/Docker-Multi--stage-2496ED?style=flat&logo=docker&logoColor=white)](https://docker.com)
[![AWS](https://img.shields.io/badge/AWS-EC2_+_ECR-FF9900?style=flat&logo=amazonaws&logoColor=white)](https://aws.amazon.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat)](LICENSE)

---

## Live Demo

**Frontend:** [http://54.156.190.134:3001](http://54.156.190.134:3001) — sign up, ingest a GitHub repo or docs URL, ask questions, chat history persists across sessions.

| Service                 | URL                                                             |
| ----------------------- | --------------------------------------------------------------- |
| Next.js frontend        | [http://54.156.190.134:3001](http://54.156.190.134:3001)           |
| Query API (Swagger)     | [http://54.156.190.134:9000/docs](http://54.156.190.134:9000/docs) |
| Ingestion API (Swagger) | [http://54.156.190.134:9001/docs](http://54.156.190.134:9001/docs) |
| Auth API (Swagger)      | [http://54.156.190.134:8004/docs](http://54.156.190.134:8004/docs) |

---

## What This Is

Most RAG tutorials stop at "chunk → embed → retrieve → generate." This project goes further, it's what a real company like [kapa.ai](https://kapa.ai) actually has to build:

- **Multi-tenant isolation** — separate Qdrant collections per tenant, JWT auth, per-tenant data isolation across all services
- **Empirically validated retrieval stack** — 12 combination chunker × retriever experiment on real docs + 78 Q&A frozen eval set
- **Production auth** — JWT access tokens (15 min) + httpOnly refresh cookie rotation (7 days), auto refresh on 401
- **Streaming answers** — SSE token-by-token generation, conversation memory, Redis cache layer
- **Chat history** — full conversation persistence in PostgreSQL, loadable from sidebar
- **MCP server** — tools exposed via the Model Context Protocol so Claude/Cursor can query the knowledge base directly
- **RAGAS-gated CI** — retrieval quality is a first-class contract; gate runs on every PR to main
- **Full CI/CD** — push to main → GitHub Actions → build 8 Docker images → push to ECR → SSH deploy to EC2

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
┌──────────────────────────────────────────────────────────────────┐
│                           Clients                                 │
│   Next.js (browser)  │  Claude/Cursor (MCP)  │  REST consumers   │
└──────┬───────────────┴──────────┬────────────┴───────────────────┘
       │                          │
  Auth Service              FastAPI services
  JWT + refresh             (auth middleware)
  /auth/signup                    │
  /auth/login              ┌──────┴────────────┐
  /auth/refresh            │   Orchestrators   │
       │                   │  QueryPipeline    │
       └───────────────────│  IngestionPipeline│
                           └──────┬────────────┘
                                  │
              ┌───────────────────▼──────────────────────┐
              │         Strategy Interfaces (Layer B)     │
              │  LLM │ Embedding │ VectorDB │ Reranker   │
              │  Cache │ Chunker │ Queue │ Storage       │
              └───────────────────┬──────────────────────┘
                                  │
              ┌───────────────────▼──────────────────────┐
              │         Implementations (Layer C)         │
              │  OpenAILLM (gpt-4o / gpt-4o-mini router) │
              │  OpenAIEmbedding (text-embedding-3-small) │
              │  TFSparseEncoder (BM25 baseline)          │
              │  QdrantDB (dense + hybrid RRF)            │
              │  CohereReranker (rerank-english-v3.0)     │
              │  RedisCache (JSON TTL)                    │
              │  HeadingAwareChunker │ CodeBlockChunker   │
              └───────────────────┬──────────────────────┘
                                  │
              ┌───────────────────▼──────────────────────┐
              │              Infrastructure               │
              │  PostgreSQL │ Qdrant │ Redis │ Celery    │
              └──────────────────────────────────────────┘
```

### 3-Layer Design

| Layer                          | What                                     | Why                                                 |
| ------------------------------ | ---------------------------------------- | --------------------------------------------------- |
| **A** — Orchestrators   | `QueryPipeline`, `IngestionPipeline` | Business logic lives here; no infra imports         |
| **B** — Interfaces      | `LLMStrategy`, `VectorDB`, etc.      | Swap implementations without touching orchestrators |
| **C** — Implementations | `OpenAILLM`, `QdrantDB`, etc.        | All infra and API calls isolated here               |

---

## Services

| Service               | Port (prod) | Description                                    |
| --------------------- | ----------- | ---------------------------------------------- |
| `auth-service`      | 8004        | JWT signup/login/refresh, tenant creation      |
| `query-service`     | 9000        | RAG query, SSE streaming, conversation history |
| `ingestion-service` | 9001        | URL/file/GitHub ingestion, job tracking        |
| `celery-worker`     | —          | Async ingestion task processing                |
| `celery-beat`       | —          | Scheduled re-ingestion tasks                   |
| `webhook-service`   | 8003        | GitHub push webhook → auto re-ingest          |
| `frontend`          | 3001        | Next.js 14 App Router frontend                 |
| `postgres`          | internal    | Users, tenants, conversations, jobs            |
| `qdrant`            | internal    | Vector storage (per-tenant collections)        |
| `redis`             | internal    | Cache + Celery broker                          |

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

## CI/CD Pipeline

```
git push origin feature/*
       │
       ▼
Pull Request → dev
       │
       ├── GitHub Actions: CI workflow
       │     ├── ruff lint
       │     ├── pytest tests/unit/ (coverage ≥ 70%)
       │     └── RAGAS quality gate (--sample 20, all 4 metrics must pass)
       │
Merge dev → main
       │
       ▼
GitHub Actions: Deploy workflow
       ├── Build 8 Docker images (multi-stage, BuildKit cache via ECR)
       ├── Push to ECR: kapa-query, kapa-ingestion, kapa-auth,
       │               kapa-frontend, kapa-celery, kapa-webhook,
       │               kapa-streamlit, kapa-mcp
       ├── SCP docker-compose.prod.yml + infra/ to EC2
       └── SSH → docker compose pull → docker compose up -d → health check
```

Every image is tagged with the git short SHA (`abc1234`) so you always know exactly which commit is deployed.

---

## Project Structure

```
kapa-inspired-rag-mcp/
├── backend/
│   ├── api/
│   │   ├── auth_service.py             # JWT signup/login/refresh
│   │   ├── ingestion_service.py        # POST /ingest, GET /ingest/{job_id}
│   │   ├── query_service.py            # POST /query, GET /conversations
│   │   └── middleware/auth.py          # JWT → tenant_id
│   ├── core/
│   │   ├── ingestion_pipeline.py
│   │   ├── query_pipeline.py
│   │   └── context_window_builder.py   # tiktoken, 6000 token budget
│   ├── strategies/                     # Layer B + C implementations
│   ├── observers/                      # Cache, Trace (LangSmith), Metrics
│   ├── repositories/                   # Postgres: tenants, jobs, conversations
│   ├── connectors/                     # DocsConnector, GitHubConnector, PDFConnector
│   └── mcp/                            # MCP server
├── frontend-next/                      # Next.js 14 App Router frontend
│   ├── app/
│   │   ├── page.tsx                    # → redirect to /login
│   │   ├── login/page.tsx
│   │   ├── signup/page.tsx
│   │   └── dashboard/page.tsx          # tabbed sidebar + chat
│   ├── components/
│   │   ├── AuthContext.tsx             # session restore on mount
│   │   ├── ChatInterface.tsx           # messages + SSE streaming
│   │   ├── PreviousChats.tsx           # conversation history sidebar
│   │   ├── AddSourcePanel.tsx          # file/GitHub/docs tabs
│   │   └── SourceList.tsx
│   └── lib/api.ts                      # authFetch with auto-refresh
├── experiments/
│   ├── 01_eval_set_generation.ipynb
│   ├── 02_docs_chunking_retrieval.ipynb
│   ├── 03_reranker_comparison.ipynb
│   └── 04_ragas_baseline.ipynb
├── eval/
│   ├── golden_dataset/docs/eval_v1.jsonl   # 78 frozen Q&A pairs
│   └── ragas_gate.py                       # CI quality gate script
├── tests/
│   ├── unit/                           # 33 unit tests (no infra needed)
│   └── integration/                    # real Qdrant + Postgres
├── infra/postgres/init.sql             # DB schema
├── .github/workflows/
│   ├── ci.yml                          # lint + unit tests + RAGAS gate
│   └── deploy.yml                      # build → ECR → EC2
├── docker-compose.yml                  # local dev
├── docker-compose.prod.yml             # production (ECR images)
├── Dockerfile                          # multi-stage: 8 targets
├── TRADEOFFS.md
└── DEPLOYMENT_NOTES.md
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

## Running Locally

### Prerequisites

- Python 3.11+, Docker + Docker Compose, Node.js 20+
- OpenAI API key, Cohere API key

### 1. Clone and install

```bash
git clone https://github.com/AyanArshad02/kapa-inspired-rag-mcp.git
cd kapa-inspired-rag-mcp
python -m venv venv && source venv/bin/activate
pip install -e ".[dev]"
```

### 2. Environment variables

```bash
cp .env.example .env
# fill in: OPENAI_API_KEY, COHERE_API_KEY, JWT_SECRET (any random string)
```

### 3. Start all services

```bash
docker compose up -d
```

### 4. Run tests

```bash
pytest tests/unit/ -v                        # unit tests, no infra needed
pytest tests/integration/ -m integration -v  # needs docker compose running
python eval/ragas_gate.py --sample 20        # RAGAS quality gate
```

### 5. Open the frontend

```
http://localhost:3001
```

Sign up → ingest a URL → ask questions.

---

## API Reference

### Auth Service (port 8004)

| Method   | Endpoint          | Description                              |
| -------- | ----------------- | ---------------------------------------- |
| `POST` | `/auth/signup`  | Create account → returns access token   |
| `POST` | `/auth/login`   | Login → returns access token            |
| `POST` | `/auth/refresh` | Rotate refresh token → new access token |
| `POST` | `/auth/logout`  | Clear refresh cookie                     |

### Ingestion Service (port 9001)

| Method     | Endpoint             | Description                                          |
| ---------- | -------------------- | ---------------------------------------------------- |
| `POST`   | `/ingest`          | Submit URL for ingestion (async, returns `job_id`) |
| `POST`   | `/ingest/upload`   | Upload a file for ingestion                          |
| `GET`    | `/ingest/{job_id}` | Poll job status                                      |
| `GET`    | `/sources`         | List all ingested sources                            |
| `DELETE` | `/ingest/upload`   | Delete a source                                      |

### Query Service (port 9000)

| Method     | Endpoint                               | Description                                                   |
| ---------- | -------------------------------------- | ------------------------------------------------------------- |
| `POST`   | `/query`                             | Ask a question —`stream: true` for SSE, `false` for JSON |
| `GET`    | `/query/conversations`               | List all conversations for this tenant                        |
| `GET`    | `/query/conversations/{id}/messages` | Load full message history                                     |
| `DELETE` | `/query/conversation/{id}`           | Clear conversation history                                    |
| `GET`    | `/health`                            | Health check                                                  |

---

## Observability

| Signal              | Implementation                                                                                              |
| ------------------- | ----------------------------------------------------------------------------------------------------------- |
| Query traces        | LangSmith — set `LANGSMITH_API_KEY` to enable                                                            |
| Prometheus metrics  | `/metrics` on all services — `rag_queries_total`, `rag_query_tokens`, `rag_source_chunks_returned` |
| Ingestion job state | PostgreSQL `ingestion_jobs` table                                                                         |
| Circuit breaker     | Built into `OpenAILLM` and `OpenAIEmbedding`                                                            |

> Prometheus + Grafana are omitted from the prod compose to fit t3.small (2GB RAM). All `/metrics` endpoints are live — add the observability stack back on t3.medium+.

---

## Experiments

The retrieval stack was chosen empirically, not by convention.

| Notebook                       | What                                         | Result                  |
| ------------------------------ | -------------------------------------------- | ----------------------- |
| `01_eval_set_generation`     | GPT-4o generates 78 Q&A pairs from real docs | Frozen eval set created |
| `02_docs_chunking_retrieval` | 12 combinations: 4 chunkers × 3 retrievers  | HAC + Dense wins on MRR |
| `03_reranker_comparison`     | Dense/Hybrid × with/without Cohere          | Reranker: +0.040 MRR    |
| `04_ragas_baseline`          | Full pipeline RAGAS evaluation               | All 4 gates passed      |

The eval set (`eval/golden_dataset/docs/eval_v1.jsonl`) is **frozen**. Ground truth is tied to 40-character text anchors — it survives chunking changes.

---

## Roadmap

- [X] **Phase 1** — Ingestion pipeline (embed + upsert + job tracking)
- [X] **Phase 2** — Query pipeline (stream + cache + conversation + RAGAS baseline)
- [X] **Phase 3** — MCP server, GitHub/PDF connectors, RAGAS CI gate
- [X] **Phase 4** — JWT auth, Next.js frontend, chat history, EC2 + CI/CD deploy
- [ ] **Phase 5** — Locust load tests, Prometheus + Grafana on t3.medium
- [ ] **Phase 6** — User-supplied GitHub tokens for private repo ingestion
- [ ] **Phase 7** — AWS upgrade: ECS Fargate, RDS, ElastiCache, ALB, blue/green

---

## System Design

Full 10-step system design in [system-design/](system-design/):

`Clarifying Questions → Functional Requirements → NFRs → Capacity Planning → HLD → Database ADR → Architecture ADRs → Pre-mortem → Implementation Plan → Class + Sequence Diagrams`

The pre-mortem identified real failure modes (BM25 paraphrase failures, JSONB asyncpg bugs, UUID tenant isolation) that were fixed before they became production issues.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Author

Built by **Ayan Arshad** · [GitHub](https://github.com/AyanArshad02)

> This project reverse-engineers the architecture behind tools like [kapa.ai](https://kapa.ai), not as a competitor, but as a rigorous exercise in building production RAG systems that are actually evaluated, not just vibes-checked.
