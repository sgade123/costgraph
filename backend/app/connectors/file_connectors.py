"""
File connectors — the reference implementation.

These load exported JSON/CSV from disk and normalize into the canonical
records. This is the fastest adoption path: export your billing, telemetry,
business metrics, and AI usage to files, point config at them, and CostGraph
runs on your data with zero code changes.

They also power the bundled App1 demo dataset (data/*.json, *.csv).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from .base import CostConnector, TelemetryConnector, BusinessConnector, AIUsageConnector
from ..schemas import CostRecord, TelemetryRecord, BusinessMetric, AIUsageEvent


def _load_json(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with p.open() as f:
        return json.load(f)


class FileCostConnector(CostConnector):
    name = "file_cost"

    def __init__(self, path: str):
        self.path = path

    def fetch(self) -> list[CostRecord]:
        return [CostRecord(**row) for row in _load_json(self.path)]


class FileTelemetryConnector(TelemetryConnector):
    name = "file_telemetry"

    def __init__(self, path: str):
        self.path = path

    def fetch(self) -> list[TelemetryRecord]:
        return [TelemetryRecord(**row) for row in _load_json(self.path)]


class FileAIUsageConnector(AIUsageConnector):
    name = "file_ai_usage"

    def __init__(self, path: str):
        self.path = path

    def fetch(self) -> list[AIUsageEvent]:
        return [AIUsageEvent(**row) for row in _load_json(self.path)]


class FileBusinessConnector(BusinessConnector):
    """Business metrics load from CSV — the format teams most often have on hand."""
    name = "file_business"

    def __init__(self, path: str):
        self.path = path

    def fetch(self) -> list[BusinessMetric]:
        p = Path(self.path)
        if not p.exists():
            return []
        out: list[BusinessMetric] = []
        with p.open() as f:
            for row in csv.DictReader(f):
                out.append(BusinessMetric(
                    timestamp=row["timestamp"],
                    product_id=row["product_id"],
                    unit_type=row["unit_type"],
                    unit_count=float(row["unit_count"]),
                    customer_id=row.get("customer_id") or None,
                    tenant_id=row.get("tenant_id") or None,
                ))
        return out
