"""Milestone 2 engine tests — deterministic, run against the seeded App1 dataset."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.repository import get_repository
from app.services.economics import compute_economics, compare_periods
from app.services.tokenomics import tokenomics


def _repo():
    get_repository.cache_clear()
    return get_repository()


def test_planes_load():
    r = _repo()
    assert len(r.cost) == 13 and len(r.telemetry) == 16
    assert len(r.business) == 2 and len(r.ai_usage) == 9


def test_in_project_matches_reference():
    r = _repo()
    e = compute_economics("app1", r.cost, r.telemetry, r.business, policy="cpu_request")
    # in-project total is the validated reference figure
    assert round(e["monthly_cost_in_project"]) == 11671


def test_policy_swing_lowers_unit_cost():
    r = _repo()
    req = compute_economics("app1", r.cost, r.telemetry, r.business, "cpu_request")
    act = compute_economics("app1", r.cost, r.telemetry, r.business, "cpu_actual")
    # actual-CPU allocation gives app1 a smaller GKE share -> lower unit cost
    assert act["cost_per_order"] < req["cost_per_order"]


def test_unit_cost_decomposes():
    r = _repo()
    e = compute_economics("app1", r.cost, r.telemetry, r.business, "cpu_request")
    parts = (e["monthly_cost_in_project"] + e["monthly_cost_cross_project"]
             + e["monthly_cost_ai"])
    assert abs(parts - e["monthly_cost_total"]) < 0.01


def test_tokenomics_cost_per_success():
    r = _repo()
    tk = tokenomics("app1", r.ai_usage, r.cost)
    # cost per successful outcome >= avg cost per invocation (failures add no value)
    assert tk["cost_per_successful_outcome"] >= tk["avg_cost_per_invocation"]
    assert 0 <= tk["success_rate"] <= 1


def test_optimizer_respects_ai_success_floor():
    from app.services.optimizer import optimize
    r = _repo()
    # strict floor above current success rate -> AI lever must be blocked
    res = optimize("app1", r.cost, r.telemetry, r.business, r.ai_usage,
                   target_unit_cost=0.05, min_ai_success_rate=0.99, protect_prod=True)
    ai_levers = [l for l in res["all_levers"] if l["type"] == "ai"]
    assert ai_levers and ai_levers[0]["constraint_respected"] is False


def test_optimizer_gates_prod_changes():
    from app.services.optimizer import optimize
    r = _repo()
    res = optimize("app1", r.cost, r.telemetry, r.business, r.ai_usage,
                   target_unit_cost=0.05, protect_prod=True)
    # the Dataflow (prod-tagged) lever must require approval
    prod_levers = [l for l in res["all_levers"] if l["touches_prod"]]
    assert prod_levers and all(l["requires_approval"] for l in prod_levers)


def test_optimizer_lowers_cost():
    from app.services.optimizer import optimize
    r = _repo()
    res = optimize("app1", r.cost, r.telemetry, r.business, r.ai_usage,
                   target_unit_cost=0.07, protect_prod=False)
    assert res["projected_unit_cost"] < res["current_unit_cost"]


def test_agent_grounded_answer():
    from app.services.agent import agent_query
    r = _repo()
    res = agent_query(r, "app1", "what does one order cost?")
    assert res["mode"] in ("llm", "deterministic")
    assert res["tool_trace"] and res["tool_trace"][0]["tool"] == "get_unit_economics"
    assert "$0.08" in res["answer"] or "0.08" in res["answer"]


def test_agent_optimize_intent():
    from app.services.agent import agent_query
    r = _repo()
    res = agent_query(r, "app1", "how do I get cost under 7 cents without hurting AI quality?")
    tools = [t["tool"] for t in res["tool_trace"]]
    assert "optimize" in tools


def test_workflow_traces():
    from app.services.workflow import workflow_traces
    r = _repo()
    w = workflow_traces("app1", r.ai_usage)
    assert w["trace_count"] == 4 and w["successful_traces"] == 3
    assert w["cost_of_failures"] > 0


def test_provider_connectors_registered():
    from app.connectors.registry import _REGISTRY
    for name in ["openai_usage", "gcp_cost", "datadog_telemetry"]:
        assert name in _REGISTRY


def test_openai_connector_gates_without_key():
    import os, pytest
    from app.connectors.provider_connectors import OpenAIUsageConnector
    old = os.environ.pop("OPENAI_API_KEY", None)
    try:
        with pytest.raises(RuntimeError):
            OpenAIUsageConnector().fetch()
    finally:
        if old:
            os.environ["OPENAI_API_KEY"] = old
