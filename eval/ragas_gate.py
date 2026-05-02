"""CI quality gate: verifies the golden eval dataset against RAGAS thresholds.

Uses source_text as the retrieved context and the stored answer as the response.
This is a dataset health check — if someone edits the golden set incorrectly, this fails.

Thresholds (set from experiment notebooks 04_ragas_baseline):
  context_recall  >= 0.75  (ground truth info covered by source_text)
  faithfulness    >= 0.70  (stored answer is faithful to source_text)

Usage:
  python eval/ragas_gate.py              # 20 samples, default thresholds
  python eval/ragas_gate.py --sample 40  # larger sample
  python eval/ragas_gate.py --strict     # thresholds +0.05 tighter
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from ragas import EvaluationDataset, SingleTurnSample, evaluate
from ragas.metrics.collections import context_recall, faithfulness

ROOT = Path(__file__).resolve().parent.parent
GOLDEN_DIRS = [
    ROOT / "eval" / "golden_dataset" / "docs" / "eval_v1.jsonl",
    ROOT / "eval" / "golden_dataset" / "github" / "eval_v1.jsonl",
]

THRESHOLDS = {"context_recall": 0.75, "faithfulness": 0.70}
STRICT_BUMP = 0.05


def load_golden(paths: list[Path]) -> list[dict]:
    rows = []
    for p in paths:
        if p.exists():
            for line in p.read_text().splitlines():
                if line.strip():
                    rows.append(json.loads(line))
    return rows


def build_dataset(rows: list[dict]) -> EvaluationDataset:
    samples = []
    for r in rows:
        samples.append(
            SingleTurnSample(
                user_input=r["question"],
                retrieved_contexts=[r["source_text"]],
                response=r["answer"],
                reference=r["answer"],
            )
        )
    return EvaluationDataset(samples=samples)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=20, help="Number of examples to evaluate")
    parser.add_argument("--strict", action="store_true", help="Raise thresholds by 0.05")
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
    result = evaluate(
        dataset=dataset,
        metrics=[context_recall, faithfulness],
        show_progress=True,
    )

    scores = {
        "context_recall": float(result["context_recall"]),
        "faithfulness": float(result["faithfulness"]),
    }

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
