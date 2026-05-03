"""ConnectorFactory — maps SourceType to the registered connector.

Adding a new source type = call `register`. Zero pipeline changes needed.
"""

from __future__ import annotations

from backend.connectors.base import ConnectorStrategy
from backend.models import SourceType


class ConnectorFactory:
    def __init__(self) -> None:
        self._registry: dict[SourceType, ConnectorStrategy] = {}

    def register(self, connector: ConnectorStrategy) -> None:
        self._registry[connector.source_type] = connector

    def get(self, source_type: SourceType) -> ConnectorStrategy:
        connector = self._registry.get(source_type)
        if connector is None:
            raise ValueError(f"No connector registered for source type: {source_type}")
        return connector
