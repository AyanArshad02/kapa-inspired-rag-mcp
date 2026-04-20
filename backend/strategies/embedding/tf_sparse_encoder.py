"""
TF-based sparse encoder — a fast, dependency-free baseline.

Maps tiktoken token IDs to normalized term-frequency weights.
Sparse indices = tiktoken token IDs (stable, no vocabulary to maintain).
Sparse values  = log-normalized TF (dampens the effect of very frequent tokens).
"""

from __future__ import annotations

import math
from collections import Counter

import tiktoken

from backend.strategies.base import SparseEncoderStrategy

_TOP_K_TOKENS = 128  # keep only the K highest-weight tokens per document


class TFSparseEncoder(SparseEncoderStrategy):
    """
    Converts text to sparse token-frequency vectors using tiktoken token IDs as indices. This is a simple, fast, and dependency-free baseline for sparse encoding.
    Tokens are tiktoken IDs so indices are consistent across all documents.
    """

    def __init__(self, top_k: int = _TOP_K_TOKENS) -> None:
        self._enc = tiktoken.encoding_for_model("gpt-4o")
        self._top_k = top_k

    async def encode(
        self, texts: list[str]
    ) -> list[tuple[list[int], list[float]]]:
        return [self._encode_one(text) for text in texts]

    def _encode_one(self, text: str) -> tuple[list[int], list[float]]:
        tokens = self._enc.encode(text)
        if not tokens:
            return [], []

        counts = Counter(tokens)
        doc_len = len(tokens)

        # log-normalized TF: dampens effect of very frequent tokens
        weighted = {
            token_id: (1 + math.log(count)) / (1 + math.log(doc_len))
            for token_id, count in counts.items()
        }

        # keep only top-K to maintain sparsity
        top = sorted(weighted.items(), key=lambda x: x[1], reverse=True)[: self._top_k]

        indices = [t[0] for t in top]
        values = [t[1] for t in top]
        return indices, values





