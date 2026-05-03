# Step 1 — Clarifying Questions

Before jumping into design, these are the clarifying questions I asked
myself to understand exactly what we are building and what constraints
we are working within.

---

## 1. Users

- Who is the primary user of this system?
- Are we building for human developers, AI agents, or both?

**Answer:** Two types of users. First, human developers who ask
technical questions while coding or reading docs and need accurate,
cited answers instantly. Second, AI coding agents (Cursor, Claude Code,
VS Code Copilot) that need live access to fresh documentation while
generating code. Both are equally important — the MCP server exists
specifically for the second type.

---

## 2. Core Action

- What is the single most critical thing this system must do well?
- If only one thing works perfectly, what should it be?

**Answer:** Return accurate, grounded, source-cited answers from
technical documentation — and say "I don't know" when the answer is
not in the knowledge base. Hallucination is the one failure mode that
kills trust completely. Everything else (speed, freshness, MCP) is
secondary to this.

---

## 3. Sources (Ingestion Scope)

- Which sources are we ingesting in v1?
- What formats are supported?
- Are we multi-tenant from day one?

**Answer:**

In Scope (v1):
- Documentation websites (crawled via sitemap or URL list)
- GitHub repositories (README, code files, markdown docs)
- PDFs (technical docs, whitepapers)
- Slack/Discord exports (JSON format)

Out of Scope (v1):
- Confluence, Notion, Jira (v2)
- Real-time Slack sync (v2 — v1 is export-based only)
- Video transcripts, audio (out of scope entirely)

Format support: Markdown, HTML, plain text, PDF, JSON exports.

Multi-tenancy: Yes, from day one. Each project/tenant gets its own
isolated namespace in the vector DB. One instance can serve multiple
knowledge bases without any data leaking across them. This mirrors exactly what I did
in Softeon multi-tenant Chatbot.

---

## 4. Scale

- How many tenants and documents are we targeting?
- How many queries per day?
- What is the expected growth trajectory?

**Answer:**

Launch (Month 1):
- 3-5 tenants (our own test projects)
- ~500 documents per tenant
- ~100 queries/day total

6 Months:
- 20-30 tenants
- ~2,000 documents per tenant
- ~2,000 queries/day total

1 Year:
- 100 tenants
- ~5,000 documents per tenant
- ~10,000 queries/day total

This is not a consumer-scale system. It is a B2B developer tool.
QPS will be low but query complexity will be high (hybrid retrieval
+ reranking + LLM call per query). Latency budget matters more than
raw throughput here.

---

## 5. Latency & Quality Targets

- What response time is acceptable?
- What quality bar are we targeting?

**Answer:**

Latency:
- p50 < 800ms end-to-end
- p95 < 2s end-to-end
- Time to first token (streaming) < 500ms

Quality:
- Faithfulness ≥ 0.90 (measured via RAGAS)
- Relevance score ≥ 0.85
- Hallucination rate < 5% on test set
- "I don't know" triggered correctly when answer not in knowledge base

These are the same targets which I hit at Softeon (0.67 → 0.91 faithfulness
jump) and are realistic with hybrid retrieval + reranking.

---

## 6. Availability

- What happens if the system goes down?
- What uptime are we targeting?

**Answer:** This is a developer tool, not a payment system. If it is
down for an hour, developers fall back to manual doc search — annoying
but not catastrophic.

Target: 99.5% uptime initially (single region, no multi-AZ).
This gives us ~44 hours downtime/year which is acceptable for v1.

As adoption grows and teams depend on it daily, we move to 99.9%
with multi-AZ deployment. We do not need 99.99% — that requires
multi-region active-active and the complexity is not justified at
this scale.

---

## 7. Freshness

- How fresh does the knowledge base need to be?
- What happens when docs change?

**Answer:** This is one of the hardest problems in production RAG
and the #1 silent failure mode (kapa.ai calls this out explicitly
in their blog).

Acceptable staleness: 24 hours for most use cases.
Critical updates (breaking API changes, deprecations): should be
reflected within 4-6 hours.

We implement two strategies and document both tradeoffs:
- Incremental re-index: Fast, cheap, but risks missing deleted content
- Full re-index: Slow, expensive, but guaranteed consistency

Scheduled: Full re-index weekly + incremental daily.

---

## 8. Boundaries (Explicit Constraints)

- What are the hard limits for v1?

**Answer:**
- No fine-tuning or custom model training
- No real-time Slack/Discord sync (export-based only in v1)
- No payment processing or billing system
- No voice or multimodal input
- English-only documents in v1
- Single region deployment in v1
- No autonomous agents (human triggers queries, agents call MCP tools)