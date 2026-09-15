"""
Repository — the single place that loads all four data planes through the
configured connectors. Every engine reads from here, so no engine is coupled
to a data source. Swap connectors in config and every engine transparently
runs on the new data.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from ..config import load_config, CostGraphConfig
from ..connectors.registry import get_connector
from ..schemas import CostRecord, TelemetryRecord, BusinessMetric, AIUsageEvent

# backend/app/services/repository.py -> parents[2] == backend/
_BACKEND_DIR = Path(__file__).resolve().parents[2]


def _resolve(source: str) -> str:
    """Sources in config are relative to the backend/ dir; make them absolute."""
    p = Path(source)
    if p.is_absolute():
        return str(p)
    return str((_BACKEND_DIR / source).resolve())


class Repository:
    def __init__(self, config: CostGraphConfig):
        self.config = config
        self._cost: list[CostRecord] | None = None
        self._telemetry: list[TelemetryRecord] | None = None
        self._business: list[BusinessMetric] | None = None
        self._ai: list[AIUsageEvent] | None = None

    def _plane(self, name: str):
        pc = self.config.planes[name]
        return get_connector(pc.connector, _resolve(pc.source))

    @property
    def cost(self) -> list[CostRecord]:
        if self._cost is None:
            self._cost = self._plane("cost").fetch()
        return self._cost

    @property
    def telemetry(self) -> list[TelemetryRecord]:
        if self._telemetry is None:
            self._telemetry = self._plane("telemetry").fetch()
        return self._telemetry

    @property
    def business(self) -> list[BusinessMetric]:
        if self._business is None:
            self._business = self._plane("business").fetch()
        return self._business

    @property
    def ai_usage(self) -> list[AIUsageEvent]:
        if self._ai is None:
            self._ai = self._plane("ai_usage").fetch()
        return self._ai


@lru_cache
def get_repository() -> Repository:
    return Repository(load_config())
