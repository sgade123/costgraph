"""
Workflow service.

Reconstructs the agentic workflow from AIUsageEvents grouped by trace_id, so the
multi-step agent flow (fraud-triage -> payments -> support) is visible end to end,
with per-step cost, tool calls, retries, and success — and the cost-per-successful
-outcome rollup that is CostGraph's AI thesis.
"""
from __future__ import annotations

from ..schemas import AIUsageEvent


def workflow_traces(product_id: str, ai_events: list[AIUsageEvent]) -> dict:
    ev = [e for e in ai_events if e.business_unit_id == product_id]
    traces: dict[str, list[AIUsageEvent]] = {}
    for e in ev:
        traces.setdefault(e.trace_id or "untraced", []).append(e)

    trace_out = []
    for tid, steps in traces.items():
        steps_sorted = sorted(steps, key=lambda s: s.timestamp)
        trace_cost = sum(s.total_ai_cost for s in steps_sorted)
        trace_success = all(s.success for s in steps_sorted)
        trace_retries = sum(s.retry_count for s in steps_sorted)
        trace_out.append({
            "trace_id": tid,
            "transaction_id": steps_sorted[0].transaction_id,
            "success": trace_success,
            "total_cost": round(trace_cost, 4),
            "total_retries": trace_retries,
            "steps": [{
                "agent": s.agent_name,
                "model": s.model,
                "tool_calls": s.tool_calls,
                "retries": s.retry_count,
                "tokens": s.input_tokens + s.output_tokens,
                "cached_tokens": s.cached_tokens,
                "cost": round(s.total_ai_cost, 4),
                "quality": s.quality_score,
                "success": s.success,
            } for s in steps_sorted],
        })

    n = len(trace_out)
    n_success = sum(1 for t in trace_out if t["success"])
    total = sum(t["total_cost"] for t in trace_out)
    return {
        "product": product_id,
        "workflow_name": ev[0].workflow_name if ev else None,
        "trace_count": n,
        "successful_traces": n_success,
        "success_rate": round(n_success / n, 4) if n else 0,
        "avg_cost_per_trace": round(total / n, 4) if n else 0,
        "cost_per_successful_trace": round(total / n_success, 4) if n_success else 0,
        "cost_of_failures": round(sum(t["total_cost"] for t in trace_out if not t["success"]), 4),
        "traces": trace_out,
    }
