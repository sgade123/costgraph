"""
AI tokenomics engine.

Turns the AI-usage plane into outcome economics: not cost-per-token, but
cost per SUCCESSFUL outcome — plus the hidden multipliers (retries, tool calls,
cache effectiveness) and model-routing economics.

The seeded AIUsageEvents are exemplars; we scale their per-outcome averages to
the product's monthly AI spend (from the cost plane) so the monthly view is
realistic without needing one row per outcome.
"""
from __future__ import annotations

from ..schemas import AIUsageEvent, CostRecord


def _monthly_ai_spend(product_id: str, cost: list[CostRecord]) -> float:
    return sum(
        c.effective_cost for c in cost
        if c.provider in ("openai", "anthropic", "google")
        and (c.labels or {}).get("app") == product_id
    )


def tokenomics(product_id: str, ai_events: list[AIUsageEvent], cost: list[CostRecord]) -> dict:
    ev = [e for e in ai_events if e.business_unit_id == product_id]
    if not ev:
        return {"product": product_id, "ai_events": 0}

    n = len(ev)
    successes = [e for e in ev if e.success]
    n_success = len(successes)
    success_rate = n_success / n if n else 0.0

    avg_cost = sum(e.total_ai_cost for e in ev) / n
    # cost per SUCCESSFUL outcome: total spend spread over only successful outcomes
    cost_per_success = (sum(e.total_ai_cost for e in ev) / n_success) if n_success else 0.0

    avg_tokens = sum(e.input_tokens + e.output_tokens for e in ev) / n
    avg_cached = sum(e.cached_tokens for e in ev) / n
    cache_rate = avg_cached / (avg_tokens + avg_cached) if (avg_tokens + avg_cached) else 0.0

    total_retries = sum(e.retry_count for e in ev)
    retry_rate = total_retries / n if n else 0.0
    # cost attributable to retries (retries repeat a model call): rough overhead estimate
    retry_overhead = sum(
        (e.total_ai_cost * (e.retry_count / (e.model_calls + e.retry_count)))
        for e in ev if (e.model_calls + e.retry_count) > 0
    )
    tool_calls_per_outcome = sum(e.tool_calls for e in ev) / n

    # model mix
    by_model: dict[str, dict] = {}
    for e in ev:
        m = by_model.setdefault(e.model, {"calls": 0, "cost": 0.0})
        m["calls"] += 1
        m["cost"] += e.total_ai_cost

    monthly_ai = _monthly_ai_spend(product_id, cost)

    return {
        "product": product_id,
        "ai_events_sampled": n,
        "success_rate": round(success_rate, 4),
        "avg_cost_per_invocation": round(avg_cost, 4),
        "cost_per_successful_outcome": round(cost_per_success, 4),
        "success_premium": round(cost_per_success - avg_cost, 4),  # what failures cost you
        "avg_tokens_per_outcome": round(avg_tokens, 1),
        "cache_hit_rate": round(cache_rate, 4),
        "retry_rate": round(retry_rate, 4),
        "retry_overhead_fraction": round((retry_overhead / sum(e.total_ai_cost for e in ev)) if ev else 0, 4),
        "tool_calls_per_outcome": round(tool_calls_per_outcome, 2),
        "model_mix": {k: {"calls": v["calls"], "cost": round(v["cost"], 4)} for k, v in by_model.items()},
        "monthly_ai_spend": round(monthly_ai, 2),
    }


def optimize_ai(tk: dict, min_success_rate: float = 0.95) -> list[dict]:
    """Suggest levers to reduce AI cost per outcome WITHOUT dropping success below floor.
    Deterministic, evidence-based suggestions derived from the tokenomics profile."""
    levers: list[dict] = []
    if tk.get("ai_events_sampled", 0) == 0:
        return levers

    if tk["cache_hit_rate"] < 0.3:
        levers.append({
            "lever": "Increase prompt caching",
            "rationale": f"Cache hit rate is {tk['cache_hit_rate']*100:.0f}%. Caching stable context could cut input-token cost materially.",
            "risk_to_success": "none",
        })
    if tk["retry_rate"] > 0.2:
        levers.append({
            "lever": "Reduce retries via schema-constrained output",
            "rationale": f"Retry rate is {tk['retry_rate']:.2f}/outcome, ~{tk['retry_overhead_fraction']*100:.0f}% of AI cost. Structured outputs reduce reparses.",
            "risk_to_success": "low — improves reliability",
        })
    # model routing: if a premium model is used where success is already high
    mix = tk.get("model_mix", {})
    if len(mix) > 1 and tk["success_rate"] >= min_success_rate:
        levers.append({
            "lever": "Route easy outcomes to a smaller model",
            "rationale": "Success rate is at/above target; a cheaper model on low-risk outcomes preserves quality while cutting cost.",
            "risk_to_success": f"bounded — hold success ≥ {min_success_rate:.0%}",
        })
    return levers
