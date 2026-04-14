# kapa-inspired-rag-mcp — Problem Statement

## The Problem

Developer-facing documentation is growing in volume and complexity faster than
any team can maintain or navigate. Engineering teams building on top of open
source projects, internal platforms, or third-party APIs spend significant time
searching across fragmented sources — official docs, GitHub issues, Slack
threads, changelogs, and PDFs — just to answer a single technical question.

This is not a search problem. Search returns links. Developers need answers —
specific, grounded, source-cited answers that account for the version they are
running, the recency of the information, and the context of their question.

## Who Is Affected (User Personas)

1. **Developer / End User** — Asks technical questions while building. Wants
an instant, accurate answer with a source citation. Does not want to read 10
docs pages to find one answer.

2. **DevRel / Docs Team** — Owns the documentation. Wants to reduce repetitive
support questions and understand what users are confused about most.

3. **Engineering Lead / CTO** — Evaluating whether to adopt or build a system
like this internally. Wants reliability, tenant isolation, cost control, and
observability.

## Why Existing Solutions Fail

| Tool | Problem |
|---|---|
| Standard search (Algolia, Ctrl+F) | Returns links, not answers. No context awareness. |
| Generic ChatGPT / Claude | Hallucinates. No grounding in your specific docs. No citations. |
| Basic RAG demos | Single source, no freshness handling, no multi-tenancy, breaks in production. |

## What This System Does

This is a production-grade RAG system built to deeply understand and implement
the hard problems that arise when you take documentation question-answering
seriously at scale:

- Multi-source ingestion (docs sites, GitHub, Slack, PDFs, tickets)
- Freshness handling — incremental re-index vs full re-index with documented
  tradeoffs
- Hybrid retrieval (dense + sparse) with reranking and grounding validation
- Tenant and project isolation for multi-team or multi-product deployments
- MCP server layer so AI agents like Claude and Cursor can query live
  documentation natively
- Full observability — latency, cost per query, retrieval quality metrics

Every architectural decision is documented with explicit tradeoffs

## Why This Was Built

Documentation question-answering at production scale is a genuinely hard
engineering problem. Most RAG implementations fail in production because they
treat it as a simple embed-and-retrieve problem.

This project exists to explore and implement the full depth of what
production-grade documentation RAG actually requires — from ingestion
architecture to retrieval quality to evaluation loops — and to document every
decision transparently.