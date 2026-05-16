# Tradeoffs & Decisions

This file records every meaningful technical decision made in this project — what was tried, what the numbers said, and why we went one way over another. Updated as experiments run.

---

## 1. Chunking Strategy for Docs Source

**Decision: HeadingAwareChunker (HAC)**

Tested on 9 real markdown files (FastAPI + Supabase docs), 78 Q&A pairs as eval set.

Full grid results:

| Chunker | Retrieval | Recall@5 | Precision@5 | MRR   |
| ------- | --------- | -------- | ----------- | ----- |
| HAC     | Hybrid    | 0.821    | 0.169       | 0.698 |
| SW-128  | Dense     | 0.821    | 0.187       | 0.687 |
| SW-128  | Hybrid    | 0.821    | 0.185       | 0.669 |
| HAC     | Dense     | 0.808    | 0.172       | 0.755 |
| SW-512  | Hybrid    | 0.808    | 0.177       | 0.688 |
| SW-256  | Hybrid    | 0.808    | 0.179       | 0.658 |
| SW-256  | Dense     | 0.808    | 0.179       | 0.656 |
| SW-512  | Dense     | 0.795    | 0.177       | 0.707 |
| SW-256  | BM25      | 0.744    | 0.164       | 0.570 |
| SW-512  | BM25      | 0.731    | 0.156       | 0.586 |
| HAC     | BM25      | 0.705    | 0.146       | 0.593 |
| SW-128  | BM25      | 0.679    | 0.156       | 0.552 |

HAC and SW-128 tie on Recall@5 (~0.82). The deciding factor was MRR. HAC+Dense gets 0.755 vs SW-128+Dense at 0.687. That gap means the answer shows up at rank 1 more often with HAC, not buried at rank 4 or 5. HAC also produces 127 chunks vs SW-128's 259 — half the chunks, same recall coverage, better ranking.

The reason is simple: docs written with headings have natural section boundaries. Splitting at those boundaries keeps related content together. Sliding windows don't know about headings, so they frequently split a paragraph mid-thought and spread the answer across two chunks.

**Not applicable for other source types.** GitHub code has no headings, Slack threads have no structure. Those will need their own chunkers and their own eval sets.

---

## 2. Retrieval Strategy for Docs Source

**Decision: Dense (OpenAI text-embedding-3-small)**

Three methods tested: BM25, Dense, Hybrid (BM25 + Dense via RRF fusion).

BM25 was consistently the worst. The failure mode is predictable — BM25 does keyword overlap, so if a query says "how to add a task" and the doc says ".add_task()", there's zero lexical match and BM25 returns nothing useful. Developer docs have this pattern constantly: queries use plain English, docs use API method names.

Dense handled the semantic gap well because text-embedding-3-small encodes meaning, not just words. "add a task" and ".add_task()" end up close in embedding space even though the strings share nothing.

Hybrid (RRF fusion of BM25 + Dense) had the best Recall@5 without a reranker (0.821 vs 0.808 for Dense alone). But its MRR was lower (0.698 vs 0.755). The right answer was retrieved more often but ranked worse — BM25's noisy signals were pulling good chunks down in the merged list.

Once the reranker was added (see next section), Dense and Hybrid converged to exactly the same scores. So Hybrid adds no benefit in this setup and dense alone is the right call — it's one model instead of two, lower latency, no BM25 index to maintain.

---

## 3. Reranker

**Decision: Cohere rerank-english-v3.0, always on**

| Pipeline              | Recall@5 | MRR   |
| --------------------- | -------- | ----- |
| HAC + Dense           | 0.808    | 0.755 |
| HAC + Hybrid          | 0.769    | 0.679 |
| HAC + Dense + Rerank  | 0.821    | 0.795 |
| HAC + Hybrid + Rerank | 0.821    | 0.795 |

The reranker had the biggest single impact of any component tested. For Dense: Recall went from 0.808 → 0.821, MRR from 0.755 → 0.795. For Hybrid: MRR went from 0.679 → 0.795 — a 0.116 jump, which is large.

The reason the Dense and Hybrid pipelines converge to the same number after reranking is that both retrieve a top-20 candidate pool with high overlap. The reranker sees roughly the same 20 chunks and picks the same top-5 from both. The retriever's job is now just "don't miss the right chunk in the top-20" rather than "rank it correctly." Dense already does that well, so Hybrid adds nothing.

Flow used in production: retrieve top-20 → Cohere reranks → take top-5.

The ~18% failure rate (14/78 questions still missed after reranking) is worth noting. Most failures come from questions where the answer spans multiple heading sections and no single HAC chunk contains the full answer. This is a known limitation of chunk-based retrieval and is partially addressed in Phase 4 by the context window builder, which can include adjacent chunks.

---


## 4. Eval Set Design

**Decision: ground truth tied to text spans, not chunk IDs**

The eval set (78 Q&A pairs, `eval/golden_dataset/docs/eval_v1.jsonl`) was generated using GPT-4o on large context windows (3000-char chunks). Each Q&A pair has a `source_text` field — a 40-character quote from the relevant passage.

A chunk is considered "relevant" if it contains that 40-char anchor text. This means the eval set works regardless of how the docs are chunked. If we switch from HAC to a different chunker tomorrow, we don't need to regenerate questions — the text anchors will match whichever chunk contains that passage.

The alternative (tying ground truth to specific chunk IDs) would make the eval set useless the moment chunking strategy changes. Text anchors are more stable because they're tied to the source document content, which doesn't change.

---

## 5. Embedding Model

**Decision: OpenAI text-embedding-3-small**

Not compared against alternatives in experiments — chose based on:

- 1536 dimensions, good quality/cost balance
- $0.02 per 1M tokens (negligible for this corpus size)
- Native support in the existing OpenAI client in the codebase
- Well-documented performance on English technical text

text-embedding-3-large (3072-dim) and Cohere embed-english-v3.0 are candidates to test in Phase 4 if RAGAS numbers don't hit targets. Not worth the added cost or complexity until there's a reason to switch.

---

## 6. Vector Database

**Decision: Qdrant (self-hosted)**

Chosen in system design. One collection per tenant (`tenant_{tenant_id}`). Hybrid search (dense + sparse) with RRF is handled natively by Qdrant, this was useful for the ingestion side but the production query path now bypasses Qdrant's built-in fusion in favor of dense-only + Cohere reranker.

Pinecone and Weaviate were considered. Qdrant was chosen because it's self-hosted (no per-vector pricing), has strong async Python support, and supports named vectors (dense + sparse in the same collection) which the hybrid experiments needed.

---

## 8. LLM (not yet decided)

Will be decided empirically in Phase 2. Candidates: gpt-4o, gpt-4o-mini. Plan is a model router, cheap model for simple factual lookups, expensive model when query complexity warrants it. RAGAS Faithfulness and AnswerRelevancy scores will determine the cutoff.

---

## 9. CI Eval Gate Metric Choice

**Decision: `context_precision` only in the PR gate; full 4-metric eval in the staging gate**

The PR gate (`ragas_gate.py`) is a **dataset health check**, not a pipeline quality check.
Its one job: detect if the golden dataset has been corrupted.

`context_precision` asks: "Is `source_text` relevant to `question`?" Clean data → ~0.75–0.80.
Corrupted `source_text` → ~0.0–0.10. Threshold set at 0.70 — wide enough gap to separate
both cases even with LLM non-determinism and random sampling variance (~±0.05 per run).

**Why not `faithfulness` or `context_recall`?**
Both metrics compare the stored answer against one `source_text` chunk. Answers were
generated in notebooks from 5 retrieved chunks — they contain information no single chunk
can support. Both score ~0.5 on perfectly clean data. Using them would produce constant
false failures with no diagnostic signal.

**The tradeoff**: `context_precision` catches source_text and question corruption, but does
NOT catch answer corruption (if someone replaces an answer with garbage). `answer_relevancy`
would catch that, but it's more expensive and the golden dataset answers are human-reviewed.
Accepted gap: answer corruption is unlikely and visually reviewable in PRs.

**Pipeline regressions** (retrieval score drops, reranker degradation) belong in the
**staging gate**, not the PR gate. The staging gate runs all 4 RAGAS metrics against the
live pipeline after deploy to staging, before prod. Cost: ~$0.20–0.50 per main merge vs
$0.03 per PR — 10× higher but only runs once per release, not once per commit.

---

## 9. Future Source Types (not yet experimented)

| Source          | Planned Chunker       | Rationale                                         |
| --------------- | --------------------- | ------------------------------------------------- |
| GitHub code     | CodeBlockAwareChunker | Function/class boundaries matter more than lines  |
| Slack / Discord | ThreadAwareChunker    | Thread = unit of context, not individual messages |
| PDF             | SlidingWindowChunker  | No structural metadata, window overlap needed     |

Each will get its own eval set and go through the same experiment pipeline (chunking → retrieval → reranker) before any production decision is made.
