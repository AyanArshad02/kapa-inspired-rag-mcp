from __future__ import annotations

from prometheus_client import Counter

rag_errors_total = Counter(
    "rag_errors_total",
    "Total errors broken down by component and error type",
    ["component", "error_type"],
)
