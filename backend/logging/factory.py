"""Factory that selects the correct LogSetup based on ENVIRONMENT.

Adding a new environment:
  1. Create backend/logging/handlers/my_env.py with a LogSetup subclass
  2. Add an entry to _REGISTRY below
  3. Done — no existing code changes
"""
from __future__ import annotations

from backend.logging.base import LogSetup


class LogSetupFactory:
    _REGISTRY: dict[str, type[LogSetup]] = {}

    @classmethod
    def _ensure_registry(cls) -> None:
        if cls._REGISTRY:
            return
        from backend.logging.handlers.dev import DevLogSetup
        from backend.logging.handlers.prod import ProdLogSetup

        cls._REGISTRY = {
            "dev": DevLogSetup,
            "prod": ProdLogSetup,
        }

    @classmethod
    def create(cls, environment: str) -> LogSetup:
        """Return a LogSetup instance for the given environment string.

        Defaults to DevLogSetup for any unknown value — fail-safe for
        local development where ENVIRONMENT may not be set.
        """
        cls._ensure_registry()
        setup_class = cls._REGISTRY.get(environment.lower(), cls._REGISTRY["dev"])
        return setup_class()
