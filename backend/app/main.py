"""
CostGraph — FastAPI application.

Exposes the deterministic engines over HTTP. All financial math happens in the
engines; these routes are thin adapters over the repository + engines.
"""
from __future__ import annotations

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .services.repository import get_repository
from .services.attribution import attribute
from .services.economics import compute_economics, compare_periods
from .services.tokenomics import tokenomics, optimize_ai
from .services.optimizer import optimize
from .services.workflow import workflow_traces
from .services.agent import agent_query

app = FastAPI(
    title="CostGraph",
    version="0.2.0",
    description="Business-flow cost attribution for cloud and AI.",
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)


@app.get("/health")
def health():
    r = get_repository()
    return {
        "status": "ok",
        "planes": {
            "cost": len(r.cost), "telemetry": len(r.telemetry),
            "business": len(r.business), "ai_usage": len(r.ai_usage),
        },
        "product": r.config.product.id,
    }


@app.get("/api/economics/{product}")
def economics(product: str, policy: str = Query("cpu_request")):
    r = get_repository()
    return compute_economics(product, r.cost, r.telemetry, r.business, policy=policy)


@app.get("/api/economics/{product}/compare")
def economics_compare(product: str, policy: str = Query("cpu_request")):
    r = get_repository()
    return compare_periods(product, r.cost, r.telemetry, r.business, policy=policy)


@app.get("/api/graph/{product}")
def graph(product: str, policy: str = Query("cpu_request")):
    r = get_repository()
    nodes, edges = attribute(product, r.cost, r.telemetry, policy=policy)
    return {
        "product": product,
        "nodes": [n.model_dump() for n in nodes],
        "edges": [e.model_dump() for e in edges],
    }


@app.get("/api/tokenomics/{product}")
def ai_tokenomics(product: str):
    r = get_repository()
    tk = tokenomics(product, r.ai_usage, r.cost)
    tk["optimization_levers"] = optimize_ai(tk, r.config.guardrails.min_ai_success_rate)
    return tk


class OptimizeRequest(BaseModel):
    target_unit_cost: float
    policy: str = "cpu_request"
    min_ai_success_rate: float | None = None
    protect_prod: bool | None = None


@app.post("/api/optimize/{product}")
def optimize_product(product: str, req: OptimizeRequest):
    r = get_repository()
    g = r.config.guardrails
    return optimize(
        product, r.cost, r.telemetry, r.business, r.ai_usage,
        target_unit_cost=req.target_unit_cost,
        policy=req.policy,
        min_ai_success_rate=req.min_ai_success_rate if req.min_ai_success_rate is not None else g.min_ai_success_rate,
        protect_prod=req.protect_prod if req.protect_prod is not None else g.protect_prod,
    )


@app.get("/api/workflow/{product}")
def workflow(product: str):
    r = get_repository()
    return workflow_traces(product, r.ai_usage)


class AgentRequest(BaseModel):
    question: str
    policy: str = "cpu_request"


@app.post("/api/agent/{product}")
def agent(product: str, req: AgentRequest):
    r = get_repository()
    return agent_query(r, product, req.question, req.policy)
