"""Loads costgraph.yaml into a typed config object."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class PlaneConfig(BaseModel):
    connector: str
    source: str


class ProductConfig(BaseModel):
    id: str
    name: str
    business_unit: str


class AllocationConfig(BaseModel):
    default_policy: str = "cpu_request"


class GuardrailsConfig(BaseModel):
    protect_prod: bool = True
    require_approval: bool = True
    min_ai_success_rate: float = 0.95


class CostGraphConfig(BaseModel):
    product: ProductConfig
    allocation: AllocationConfig
    guardrails: GuardrailsConfig
    planes: dict[str, PlaneConfig]


_DEFAULT_PATH = Path(__file__).parent / "config" / "costgraph.yaml"


def load_config(path: str | Path | None = None) -> CostGraphConfig:
    p = Path(path) if path else _DEFAULT_PATH
    with p.open() as f:
        raw: dict[str, Any] = yaml.safe_load(f)
    return CostGraphConfig(**raw)
