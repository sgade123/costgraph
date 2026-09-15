"""
CostGraph — connector contract.

A connector's ONLY job is to normalize one provider's raw data into the
four canonical record types (schemas.py). Everything above the connector
layer is provider-agnostic.

To onboard your own data you implement one subclass per plane you have,
register it, and point config at it. You never modify the engines.

    class MyGcpCostConnector(CostConnector):
        provider = "gcp"
        def fetch(self) -> list[CostRecord]:
            rows = query_bigquery_billing_export(...)
            return [self._normalize(r) for r in rows]

See file_connectors.py for a complete, working reference implementation that
loads exported JSON/CSV — the fastest path to adopting CostGraph with your
own data is to export your billing/telemetry to files and use those.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from ..schemas import CostRecord, TelemetryRecord, BusinessMetric, AIUsageEvent


class Connector(ABC):
    """Base for all connectors. `name` identifies the connector in config."""
    name: str = "base"
    plane: str = "base"


class CostConnector(Connector):
    plane = "cost"

    @abstractmethod
    def fetch(self) -> list[CostRecord]:
        """Return normalized cost records for the reporting period."""
        raise NotImplementedError


class TelemetryConnector(Connector):
    plane = "telemetry"

    @abstractmethod
    def fetch(self) -> list[TelemetryRecord]:
        """Return normalized consumption/telemetry records for the period."""
        raise NotImplementedError


class BusinessConnector(Connector):
    plane = "business"

    @abstractmethod
    def fetch(self) -> list[BusinessMetric]:
        """Return normalized business-unit counts (the denominator)."""
        raise NotImplementedError


class AIUsageConnector(Connector):
    plane = "ai_usage"

    @abstractmethod
    def fetch(self) -> list[AIUsageEvent]:
        """Return normalized AI/LLM usage events for the period."""
        raise NotImplementedError
