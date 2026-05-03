# Chunking × Retrieval Evaluation Analysis for Docs source

## Goal
Evaluate different combinations of:
- Chunking strategies
- Retrieval methods

to understand their impact on retrieval performance

---

# 1. Experiment Setup

### Chunkers Tested
- HeadingAwareChunker (HAC)
- Sliding Window (128, 256, 512)

### Retrievers Tested
- BM25
- Dense
- Hybrid (BM25 + Dense via RRF)

### Metrics
- Recall@5 → Can we find the answer?
- MRR → How early does the answer appear?
- Precision@5 → How clean are the top results?

---

# 2. Key Observations

## Chunking

- HAC and SW-128 achieve similar Recall (~0.82)
- HAC significantly outperforms SW-128 in MRR
- HAC produces ~50% fewer chunks for the similar recall

Interpretation:
- HAC preserves semantic structure (via headings)
- Sliding windows introduce noise

---

## Retrieval

### Dense Retrieval
- Best MRR (0.755)
- Slightly lower Recall (~0.808)

### Hybrid Retrieval
- Best Recall (~0.821)
- Lower MRR (~0.698)

### BM25
- Worst performance overall
- Fails on paraphrased queries

---

# 3. Insights

## Dense vs Hybrid Tradeoff

- Dense → better ranking (higher MRR)
- Hybrid → better coverage (higher Recall)

Hybrid introduces noise due to BM25 signals, which:
- Helps find more answers
- But pushes correct answers lower in ranking

---

## BM25 Limitation

BM25 relies on keyword matching.

Example:
- Query: "how to add a task"
- Doc: ".add_task()"

No lexical overlap → retrieval failure

---

# 4. Important Limitation of Current Setup

Current pipeline:

Query → Retrieval → Top-K → Evaluation

Missing component: Reranker

---

# 5. Why This Matters

Without a reranker:

- Retrieval must handle both:
  - Finding relevant chunks
  - Ranking them correctly

This penalizes Hybrid unfairly.

---

# 6. Expected Behavior with Reranker

Future pipeline:

Query → Retrieval (Top-20) → Reranker → Top-5 → Evaluation

Expected:

- Dense → strong baseline
- Hybrid → likely better after reranking

Reason:
- Hybrid improves candidate pool (Recall)
- Reranker fixes ranking noise

---

# 7. Current Status (NO FINAL DECISION)

## Chunking
- HAC is the strongest candidate

## Retrieval (without reranker)
- Dense performs best in ranking (MRR)
- Hybrid performs best in coverage (Recall)

No final decision yet - still need to experiment after adding reranker

---

# 8. Next Experiment

We will evaluate:

1. HAC + Dense + Reranker
2. HAC + Hybrid + Reranker

### Setup

- Retrieve Top-20 chunks
- Apply reranker
- Select Top-5
- Compute metrics

---

# 9. Evaluation Targets

- Recall@5 ≥ 0.82
- MRR ≥ 0.80
