"""
Agent service.

Turns a natural-language question into calls against the deterministic engines,
then composes an answer. Two modes, chosen automatically:

  * LLM mode (if OPENAI_API_KEY is set): an LLM interprets the question, picks
    which tools to call, and writes the final explanation. The LLM NEVER computes
    a number — it only orchestrates the deterministic engines and explains their
    output. This is the "deterministic core, AI on top" principle.

  * Deterministic fallback (no key): rule-based intent routing maps the question
    to the right engine(s). The demo always works, key or not.

Either way the response includes a `tool_trace` — the exact engine calls made and
what they returned — so the answer is auditable and provably grounded.
"""
from __future__ import annotations

import json
import os
from typing import Any

from .repository import Repository
from .economics import compute_economics, compare_periods
from .tokenomics import tokenomics
from .optimizer import optimize
from .workflow import workflow_traces


# --------------------------------------------------------------------------- #
#  Tools the agent can call — each wraps a deterministic engine.              #
# --------------------------------------------------------------------------- #
def _tools(repo: Repository, product: str, policy: str):
    return {
        "get_unit_economics": {
            "desc": "Cost per completed order, decomposed into in-project / cross-project / AI.",
            "run": lambda: compute_economics(product, repo.cost, repo.telemetry, repo.business, policy=policy),
        },
        "get_ai_tokenomics": {
            "desc": "AI cost per successful outcome; cache, retry, tool-call overhead; model mix.",
            "run": lambda: tokenomics(product, repo.ai_usage, repo.cost),
        },
        "get_workflow_traces": {
            "desc": "The agentic workflow trace (fraud-triage -> payments -> support): per-step cost, retries, success.",
            "run": lambda: workflow_traces(product, repo.ai_usage),
        },
        "compare_periods": {
            "desc": "Why unit cost changed vs last month, with the primary driver.",
            "run": lambda: compare_periods(product, repo.cost, repo.telemetry, repo.business, policy=policy),
        },
        "optimize": {
            "desc": "Ranked levers to hit a target unit cost, respecting AI-success floor and prod guardrails.",
            "run": lambda target=0.07: optimize(product, repo.cost, repo.telemetry, repo.business,
                                                repo.ai_usage, target_unit_cost=target,
                                                policy=policy,
                                                min_ai_success_rate=repo.config.guardrails.min_ai_success_rate,
                                                protect_prod=repo.config.guardrails.protect_prod),
        },
    }


# --------------------------------------------------------------------------- #
#  Deterministic intent routing (fallback, no LLM)                            #
# --------------------------------------------------------------------------- #
def _route(question: str) -> list[str]:
    q = question.lower()
    picks: list[str] = []
    if any(w in q for w in ["optimi", "reduce", "lower", "cut cost", "target", "cheaper",
                            "save", "under", "below", "get it to", "bring it", "hit "]):
        picks.append("optimize")
    if any(w in q for w in ["why", "change", "went up", "increase", "last month", "rose", "driver"]):
        picks.append("compare_periods")
    if any(w in q for w in ["ai", "token", "model", "agent cost", "llm", "successful outcome",
                            "retry", "cache", "quality"]):
        picks.append("get_ai_tokenomics")
    if any(w in q for w in ["workflow", "trace", "steps", "fraud", "payment", "support",
                            "end to end", "end-to-end", "pipeline"]):
        picks.append("get_workflow_traces")
    if any(w in q for w in ["cost", "order", "unit", "how much", "spend", "economics"]) or not picks:
        picks.insert(0, "get_unit_economics")
    seen, out = set(), []
    for p in picks:
        if p not in seen:
            seen.add(p); out.append(p)
    return out


def _explain_deterministic(question: str, results: dict[str, Any]) -> str:
    parts: list[str] = []
    if "get_unit_economics" in results:
        e = results["get_unit_economics"]
        parts.append(
            f"One {e['business_unit']} costs ${e['cost_per_order']:.4f} under {e['allocation_policy']} allocation "
            f"(${e['cost_per_order_in_project']:.4f} in-project, ${e['cost_per_order_cross_project']:.4f} cross-project, "
            f"${e['cost_per_order_ai']:.4f} AI). That's ${e['monthly_cost_total']:,.0f}/mo across "
            f"{e['completed_orders']:,.0f} orders."
        )
    if "get_ai_tokenomics" in results:
        t = results["get_ai_tokenomics"]
        parts.append(
            f"AI costs ${t['cost_per_successful_outcome']:.4f} per successful outcome at a "
            f"{t['success_rate']*100:.0f}% success rate; cache hit {t['cache_hit_rate']*100:.0f}%, "
            f"retry rate {t['retry_rate']:.2f}/outcome."
        )
    if "get_workflow_traces" in results:
        w = results["get_workflow_traces"]
        parts.append(
            f"The {w['workflow_name']} workflow ran {w['trace_count']} traces ({w['successful_traces']} successful). "
            f"Cost per successful trace is ${w['cost_per_successful_trace']:.4f}; "
            f"${w['cost_of_failures']:.4f} went to failed runs."
        )
    if "compare_periods" in results:
        c = results["compare_periods"]
        parts.append(
            f"Unit cost went from ${c['previous_cost_per_order']:.4f} to ${c['current_cost_per_order']:.4f} "
            f"({c['change_pct']:+.1f}%). {c['primary_driver']}"
        )
    if "optimize" in results:
        o = results["optimize"]
        parts.append(o["summary"] + f" Recommended levers: " +
                     "; ".join(l["lever"] for l in o["recommended_levers"]) + ".")
        blocked = [l for l in o["all_levers"] if l.get("constraint_respected") is False]
        if blocked:
            parts.append(f"Blocked (would breach quality floor): {blocked[0]['lever']}.")
    return " ".join(parts)


# --------------------------------------------------------------------------- #
#  LLM path (OpenAI)                                                          #
# --------------------------------------------------------------------------- #
def _answer_llm(question: str, tool_results: dict[str, Any]) -> str | None:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    try:
        import httpx
        system = (
            "You are CostGraph's FinOps analyst. Answer the user's question using ONLY the "
            "tool results provided (real numbers from deterministic engines). Never invent numbers. "
            "Be concise and specific, cite the figures, and explain what they mean for cost per outcome."
        )
        content = f"Question: {question}\n\nTool results (ground truth):\n{json.dumps(tool_results, indent=2)}"
        r = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": os.getenv("COSTGRAPH_LLM_MODEL", "gpt-4o-mini"),
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": content}],
                "temperature": 0.2,
            },
            timeout=30,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None  # graceful fallback


# --------------------------------------------------------------------------- #
#  Public entry                                                               #
# --------------------------------------------------------------------------- #
def agent_query(repo: Repository, product: str, question: str, policy: str = "cpu_request") -> dict:
    tools = _tools(repo, product, policy)
    picks = _route(question)

    tool_trace = []
    results: dict[str, Any] = {}
    for name in picks:
        if name not in tools:
            continue
        out = tools[name]["run"]()
        results[name] = out
        # keep the trace compact — headline numbers, not full payloads
        tool_trace.append({
            "tool": name,
            "description": tools[name]["desc"],
            "returned": _summarize(name, out),
        })

    llm_answer = _answer_llm(question, results)
    answer = llm_answer or _explain_deterministic(question, results)
    return {
        "question": question,
        "answer": answer,
        "mode": "llm" if llm_answer else "deterministic",
        "tool_trace": tool_trace,
    }


def _summarize(name: str, out: dict) -> dict:
    """Compact headline of a tool's result, for the visible trace."""
    if name == "get_unit_economics":
        return {"cost_per_order": out["cost_per_order"], "total": out["monthly_cost_total"]}
    if name == "get_ai_tokenomics":
        return {"cost_per_successful_outcome": out["cost_per_successful_outcome"], "success_rate": out["success_rate"]}
    if name == "get_workflow_traces":
        return {"traces": out["trace_count"], "cost_per_successful_trace": out["cost_per_successful_trace"]}
    if name == "compare_periods":
        return {"change_pct": out["change_pct"]}
    if name == "optimize":
        return {"projected": out["projected_unit_cost"], "target_met": out["target_met"],
                "levers": len(out["recommended_levers"])}
    return {}
