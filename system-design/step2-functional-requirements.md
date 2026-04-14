# Step 2 — Functional Requirements

I focused on writting this as user journeys with success criteria, not just
a feature list.

---

## CORE FEATURES — Must Have (v1)

### FR1: Document Ingestion
User (tenant admin) provides a source (docs URL, GitHub repo link,
PDF, Slack export) → system pulls the content, cleans it, chunks it,
generates embeddings, and stores it in an isolated namespace.

Success criteria:
- Ingestion completes without manual intervention
- Each chunk carries metadata: source URL, timestamp, document title,
  chunk index, tenant ID
- Duplicate documents are detected and skipped (not re-indexed)
- Failed ingestion jobs are logged with the exact reason for failure
- Supported formats: Markdown, HTML, plain text, PDF, JSON exports

### FR2: Freshness Handling (Incremental + Full Re-index)
System detects when source content has changed → triggers the right
update strategy automatically.

Success criteria:
- Incremental re-index: only changed/new documents are re-processed
  (runs daily)
- Full re-index: entire knowledge base is rebuilt from scratch
  (runs weekly/)
- Deleted documents are removed from the vector index on full re-index
- Each re-index job is logged with: documents processed, time taken,
  chunks updated, errors encountered
- Staleness never exceeds 24 hours under normal operation

### FR3: Hybrid Retrieval
User submits a natural language query → system retrieves the most
relevant chunks using both dense (semantic) and sparse (keyword/BM25)
retrieval, then merges the results using RRF

Success criteria:
- Dense retrieval: embedding-based similarity search in vector DB
- Sparse retrieval: BM25 keyword search over the same corpus
- Results from both are merged using Reciprocal Rank Fusion (RRF)
- Top-K chunks (configurable, default K=20) passed to reranker
- Retrieval step completes in < 200ms at p95 

### FR4: Reranking + Source Prioritization
After retrieval, chunks are reranked by a cross-encoder model to
improve precision. Sources are also prioritized (official docs >
GitHub issues > Slack threads).

Success criteria:
- Top 20 retrieved chunks → reranked → top 5 passed to LLM
- Source priority is configurable per tenant
- Reranking adds < 200ms additional latency at p95
- Reranker model should be swappable without changing pipeline logic

### FR5: Grounded Answer Generation
System builds a context window from top-5 chunks → calls LLM →
generates a grounded answer with inline citations pointing to source
URLs.

Success criteria:
- Context window includes top-5 retrieved chunks + last 3 conversation
  turns (injected from session history before LLM call)
- Every factual claim in the answer is tied to a source chunk
- If retrieved chunks do not contain the answer, system responds with
  "I don't know based on available documentation" — never hallucinates
- Answer includes: response text, source URLs, confidence score
- LLM call completes in < 1,500ms at p95 (streaming starts < 500ms)
- System prompt is version-controlled and tested before every change

### FR6: Multi-Tenant Project Isolation
Multiple tenants (teams/projects) can use one instance of the system
with zero data leakage between them.

Success criteria:
- Each tenant gets an isolated namespace in the vector DB
- Every query is scoped to the requesting tenant's namespace only
- Tenant ID is derived from API key — never trusted from request body
- Cross-tenant access is impossible at the DB layer, not just app layer
- Adding a new tenant requires no downtime or schema migration

### FR7: REST API
System exposes a clean REST API for humans and services to interact
with the RAG pipeline.

Success criteria:
Endpoints:
  POST /ingest              → trigger ingestion for a source
  GET  /ingest/{job_id}     → check ingestion job status
  POST /query               → submit a question, get grounded answer
  GET  /health              → system health check
  GET  /metrics             → retrieval + quality metrics per tenant
  POST /sessions            → create a new session, returns session_id
  DELETE /sessions/{id}     → expire a session manually

- All endpoints require API key authentication
- Rate limiting enforced per tenant (configurable)
- All responses follow consistent JSON schema with error codes

### FR8: MCP Server
System exposes an MCP (Model Context Protocol) server so AI coding
agents (Cursor, Claude Code, VS Code) can query the knowledge base
live while writing code.

Success criteria:
- MCP server exposes two tools:
  1. search_knowledge_base(query, tenant_id) → returns grounded answer
     + source citations
  2. fetch_and_query_online_docs(url, query) → fetches live URL,
     builds temporary index, answers query, caches for 30 minutes
- MCP server connects in one click from Cursor/Claude Code
- MCP tool calls go through the same RAG pipeline as REST API
  (no separate logic)
- Tool responses include source URLs so agent can reference them

### FR9: Evaluation Pipeline
System runs automated quality checks on the RAG pipeline using RAGAS
metrics so we always know if quality is degrading.

Success criteria:
- Metrics tracked per query: faithfulness, answer relevance, context
  precision, context recall
- Golden dataset of 100+ query-answer pairs maintained per tenant
- Evaluation runs automatically after every prompt change or model
  update
- Dashboard shows metric trends over time
- Deployment is blocked if faithfulness drops below 0.85

### FR10: Observability
Every query is fully traceable from input to output so debugging
and quality improvement is possible.

Success criteria:
- Every query logged with: input query, rewritten query, retrieved
  chunks, reranker scores, LLM response, latency breakdown, cost,
  cache hit/miss, tenant ID
- LangSmith integration for full trace visibility
- Prometheus metrics exposed for: QPS, p50/p95/p99 latency, error
  rate, cache hit rate, LLM cost per query
- Grafana dashboard with: service health, quality metrics, cost
  per tenant

---

## NICE TO HAVE — v2

- Confluence, Notion, Jira connectors
- Real-time Slack sync (webhook-based, not export-based)
- Web UI / chat widget for non-API users
- Semantic caching (embedding-based, not just exact match)
- Per-tenant custom reranking weights

---

## OUT OF SCOPE — Explicitly Not Building

- Fine-tuning or custom model training
- Voice or multimodal input
- Payment processing or billing system
- Mobile app
- Multi-region deployment (v1 is single region)
- Autonomous agents (system responds to queries, does not initiate)