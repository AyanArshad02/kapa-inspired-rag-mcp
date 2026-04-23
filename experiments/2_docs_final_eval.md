# Final Evaluation — Chunking × Retrieval × Reranker

## Goal
Evaluate the impact of:
- Chunking strategy
- Retrieval method
- Reranking

on overall retrieval performance in a RAG pipeline.

---

# 1. Final Results

| Pipeline | Recall@5 | Precision@5 | MRR |
|---------|----------|-------------|-----|
| HAC + Dense | 0.808 | 0.172 | 0.755 |
| HAC + Hybrid | 0.769 | 0.159 | 0.679 |
| HAC + Dense + Rerank | **0.821** | 0.172 | **0.795** |
| HAC + Hybrid + Rerank | **0.821** | 0.172 | **0.795** |

---

# 2. Key Observations

## Impact of Reranker

- Adding reranker improves:
  - Recall@5: 0.808 → 0.821
  - MRR: 0.755 → 0.795

Reranker significantly improves ranking quality and answer retrieval.

---

## Dense vs Hybrid (Without Reranker)

- Dense outperforms Hybrid:
  - Higher MRR (0.755 vs 0.679)
  - Higher Recall (0.808 vs 0.769)

Hybrid introduces noise due to weak BM25 signals.

---

## Dense vs Hybrid (With Reranker)

- Both pipelines converge to identical performance:
  - Recall@5 = 0.821
  - MRR = 0.795

Retrieval differences disappear after reranking.

---

# 3. Interpretation

## Reranker-Dominated Regime

Pipeline:

Query → Retrieve (Top-20) → Rerank → Top-5

Final ranking is determined by the reranker, not the retriever.

---

## Candidate Overlap

- Dense and Hybrid retrieve highly overlapping candidate sets
- Reranker selects the same top chunks from both

This leads to identical final metrics.

---

## Hybrid Limitation

Hybrid = Dense + BM25

Observed behavior:
- BM25 underperforms due to paraphrased queries
- Adds noise instead of useful signal

Hybrid does not improve candidate quality in this setup.

---

# 4. Final Conclusions

## Chunking

HeadingAwareChunker (HAC) is the optimal choice because:
- Preserves semantic structure
- Achieves higher MRR
- Produces fewer chunks → more efficient

---

## Retrieval

Dense retrieval is sufficient:
- Strong semantic matching
- Provides high-quality candidates for reranker
- Hybrid does not add value in current setup

---

## Reranker

Reranker is the most impactful component:
- Improves both Recall and MRR
- Eliminates differences between retrieval strategies
- Dominates final ranking quality

---

# 5. Key Insight

Once a strong reranker is introduced, retrieval strategy becomes less critical as long as it provides a good candidate pool.

---

# 6. Final Pipeline

HAC → Dense Retrieval (Top-20) → Reranker → Top-5 → LLM

- Choose Dense over Hybrid for the production pipeline because:

  - Identical final performance (0.821 Recall, 0.795 MRR)
  - Dense = one model, no BM25 index to maintain
  - Simpler system, lower latency (no sparse encoding step)
  - Hybrid adds complexity with zero benefit once reranker is present


- Final stack for docs source:

  - docs (.md/.mdx)
      → HeadingAwareChunker
      → text-embedding-3-small (dense)
      → top-20 retrieval
      → Cohere rerank-english-v3.0
      → top-5 to LLM

---

# 7. When Hybrid Might Help

Hybrid retrieval may be useful if:
- Corpus size is very large
- Exact keyword matching is critical
- Dense retrieval misses specific edge cases

Not applicable in the current setup

---

# 8. Next Steps

- Increase candidate pool (Top-20 → Top-30)
- Analyze failure cases (~18% misses)
- Improve evaluation dataset quality
- Integrate full RAG pipeline (LLM generation)




