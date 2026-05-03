from __future__ import annotations

import logging

from backend.config import settings
from backend.models import ContextWindow, QueryResult
from backend.observers.base import QueryObserver

logger = logging.getLogger(__name__)


class TraceObserver(QueryObserver):
    """Sends query traces to LangSmith for debugging and evaluation.

    If the LangSmith API key is not set, tracing is silently skipped —
    the observer is always safe to include in the pipeline.
    """

    def __init__(self) -> None:
        self._enabled = bool(settings.langsmith_api_key)
        if self._enabled:
            try:
                from langsmith import Client
                self._client = Client(api_key=settings.langsmith_api_key)
            except ImportError:
                logger.warning("langsmith package not installed — tracing disabled")
                self._enabled = False

    async def notify(self, context: ContextWindow, result: QueryResult) -> None:
        if not self._enabled:
            return
        try:
            self._client.create_run(
                name="rag_query",
                run_type="chain",
                inputs={
                    "query": context.query,
                    "tenant_id": context.tenant_id,
                    "num_chunks": len(context.chunks),
                    "total_tokens": context.total_tokens,
                },
                outputs={
                    "answer": result.answer,
                    "cached": result.cached,
                    "num_source_chunks": len(result.source_chunks),
                },
            )
        except Exception as exc:
            logger.warning("LangSmith trace failed: %s", exc)
