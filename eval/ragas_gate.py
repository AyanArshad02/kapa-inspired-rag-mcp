"""CI quality gate: verifies the golden eval dataset against RAGAS thresholds.

Uses source_text as the retrieved context and the stored answer as the response.
This is a DATASET HEALTH CHECK — if someone edits the golden set incorrectly,
this fails.

WHY context_precision and NOT faithfulness/context_recall:
  context_precision asks: "is this source_text relevant to this question?"
  For a clean golden dataset, source_text was specifically chosen as the source
  for each question, so precision should be ~1.0.
  If someone corrupts source_text (replaces it with garbage), precision drops to ~0.

  faithfulness/context_recall score the LLM answer against ONE source chunk.
  Answers in the golden set were generated from larger context (often multiple
  chunks), so they contain more information than any single chunk can support.
  Those metrics are designed for live pipeline evaluation, not dataset health.

Thresholds (validated on 20-sample golden dataset run):
  context_precision >= 0.90  (source_text must be clearly relevant to question)

Usage:
  python eval/ragas_gate.py              # 20 samples, default threshold
  python eval/ragas_gate.py --sample 40  # larger sample
  python eval/ragas_gate.py --strict     # threshold +0.05 tighter
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import context_precision

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIRS = [
    ROOT / "eval" / "golden_dataset" / "docs" / "eval_v1.jsonl",
    ROOT / "eval" / "golden_dataset" / "github" / "eval_v1.jsonl",
]

THRESHOLDS = {"context_precision": 0.90}
STRICT_BUMP = 0.05


def load_golden(paths: list[Path]) -> list[dict]:
    rows = []
    for p in paths:
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip():
                    rows.append(json.loads(line))
    return rows


def build_dataset(rows: list[dict]) -> Dataset:
    return Dataset.from_dict(
        {
            "question": [r["question"] for r in rows],
            "contexts": [
                [r.get("source_text") or r.get("source_chunk", "")] for r in rows
            ],
            "ground_truth": [r["answer"] for r in rows],
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=20, help="Number of examples to evaluate")
    parser.add_argument("--strict", action="store_true", help="Raise threshold by 0.05")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    thresholds = {
        k: v + (STRICT_BUMP if args.strict else 0.0) for k, v in THRESHOLDS.items()
    }

    rows = load_golden(GOLDEN_DIRS)
    if not rows:
        print("ERROR: No golden dataset files found.", file=sys.stderr)
        sys.exit(1)

    random.seed(args.seed)
    sample = random.sample(rows, min(args.sample, len(rows)))
    print(f"Loaded {len(rows)} total examples — evaluating {len(sample)} samples")

    dataset = build_dataset(sample)
    result = evaluate(dataset, metrics=[context_precision])

    scores = {"context_precision": float(result["context_precision"])}

    print("\n── RAGAS Gate Results ────────────────────────────────────────")
    passed = True
    for metric, score in scores.items():
        threshold = thresholds[metric]
        status = "PASS" if score >= threshold else "FAIL"
        if score < threshold:
            passed = False
        print(f"  {metric:<20} {score:.3f}  (threshold={threshold:.2f})  [{status}]")
    print("─────────────────────────────────────────────────────────────")

    if not passed:
        print("\nRAGAS gate FAILED — one or more metrics below threshold.", file=sys.stderr)
        sys.exit(1)

    print("\nRAGAS gate PASSED.")


if __name__ == "__main__":
    main()
