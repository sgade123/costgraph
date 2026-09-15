"""
Connector registry — resolves the connectors named in costgraph.yaml to
concrete connector instances. Register a new connector here (or via
`register()`) to make it available to config.
"""
from __future__ import annotations

from typing import Callable

from .base import Connector
from .file_connectors import (
    FileCostConnector,
    FileTelemetryConnector,
    FileBusinessConnector,
    FileAIUsageConnector,
)
from .provider_connectors import (
    OpenAIUsageConnector,
    GcpCostConnector,
    GcpCsvCostConnector,
    DatadogTelemetryConnector,
)

# name -> factory(source_path) -> Connector
_REGISTRY: dict[str, Callable[[str], Connector]] = {
    "file_cost": FileCostConnector,
    "file_telemetry": FileTelemetryConnector,
    "file_business": FileBusinessConnector,
    "file_ai_usage": FileAIUsageConnector,
    # provider connectors (real + reference)
    "openai_usage": OpenAIUsageConnector,       # REAL — needs OPENAI_API_KEY (admin)
    "gcp_cost": GcpCostConnector,               # REAL — BigQuery billing export
    "gcp_csv_cost": GcpCsvCostConnector,        # REAL — downloaded billing CSV (no creds)
    "datadog_telemetry": DatadogTelemetryConnector,  # reference — needs DD keys
}


def register(name: str, factory: Callable[[str], Connector]) -> None:
    """Register a custom connector so config can reference it by name."""
    _REGISTRY[name] = factory


def get_connector(name: str, source: str) -> Connector:
    if name not in _REGISTRY:
        raise KeyError(
            f"Unknown connector '{name}'. Registered: {sorted(_REGISTRY)}. "
            f"Add yours in connectors/registry.py or via register()."
        )
    return _REGISTRY[name](source)
