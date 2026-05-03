"""Abstract base for all logging setup strategies.

Mirrors the Strategy Pattern used across the rest of the codebase
(VectorDBStrategy, LLMStrategy, etc.).

Extending:
  1. Create a new file under backend/logging/handlers/
  2. Subclass LogSetup and implement configure()
  3. Register the new class in LogSetupFactory with its environment key

Nothing else changes. The service startup events call
LogSetupFactory.create(settings.environment).configure(service_name)
and never import a concrete handler directly.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class LogSetup(ABC):
    """Contract that every logging backend must satisfy.

    configure() is called once from each service's startup event,
    after uvicorn has finished its own logging initialisation.
    """

    @abstractmethod
    def configure(self, service_name: str) -> None:
        """Attach handlers and set levels for the given service.

        Args:
            service_name: logical name of the service (e.g. "ingestion",
                          "query", "celery"). Used for the log file name
                          in dev and the CloudWatch log stream name in prod.
        """
        ...
