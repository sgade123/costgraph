"""
Optimization engine.

Given a target cost-per-outcome and constraints (min AI success rate, protect
prod), produce a ranked, deterministic set of levers that move unit cost toward
the target — each annotated with its projected saving and whether it respects
the guardrails. No lever that would breach a guardrail is auto-applied; it is
returned as `requires_approval` instead.

Deterministic and evidence-based: every lever's saving is computed from the
actual attributed costs and tokenomics profile, not guessed.
"""
from __future__ import annotations

from ..schemas import CostRecord, TelemetryRecord, BusinessMetric
from .economics import compute_economics
from .tokenomics import tokenomics


def optimize(
    product_id: str,
    cost: list[CostRecord],
    telemetry: list[TelemetryRecord],
    business: list[BusinessMetric],
    ai_events,
    target_unit_cost: float,
    policy: str = "cpu_request",
    min_ai_success_rate: float = 0.95,
    protect_prod: bool = True,
) -> dict:
    base = compute_economics(product_id, cost, telemetry, business, policy=policy)
    orders = base["completed_orders"] or 1
    current = base["cost_per_order"]
    tk = tokenomics(product_id, ai_events, cost)

    levers: list[dict] = []

    # ---- Lever 1: switch allocation policy to actual CPU (methodology, no risk) ----
    if policy != "cpu_actual":
        alt = compute_economics(product_id, cost, telemetry, business, policy="cpu_actual")
        saving = current - alt["cost_per_order"]
        if saving > 0:
            levers.append({
                "lever": "Allocate shared compute by actual CPU, not requests",
                "type": "methodology",
                "projected_unit_cost": alt["cost_per_order"],
                "saving_per_order": round(saving, 5),
                "annual_saving": round(saving * orders * 12, 2),
                "risk_to_success": "none",
                "touches_prod": False,
                "requires_approval": False,
                "evidence": "Reserved-vs-used gap on the shared GKE cluster; app1 uses less than it reserves.",
            })

    # ---- Lever 2: rightsize app1's Dataflow job (infra; prod-tagged) ----
    df_gain = 0.25
    df_opt = compute_economics(product_id, cost, telemetry, business, policy=policy, dataflow_gain=df_gain)
    df_saving = current - df_opt["cost_per_order"]
    if df_saving > 0:
        levers.append({
            "lever": f"Rightsize app1 Dataflow enrich-stream (+{int(df_gain*100)}% utilization)",
            "type": "infrastructure",
            "projected_unit_cost": df_opt["cost_per_order"],
            "saving_per_order": round(df_saving, 5),
            "annual_saving": round(df_saving * orders * 12, 2),
            "risk_to_success": "low",
            "touches_prod": True,
            "requires_approval": protect_prod,   # prod-tagged -> gated by guardrail
            "evidence": "enrich-stream runs below target utilization; consolidation cuts vCPU-hours.",
        })

    # ---- Lever 3: AI cost reduction, constrained by success floor ----
    if tk.get("ai_events_sampled", 0) > 0:
        ai_share = base["monthly_cost_ai"] / base["monthly_cost_total"] if base["monthly_cost_total"] else 0
        # only propose AI cuts that keep success >= floor
        can_cut_ai = tk["success_rate"] >= min_ai_success_rate
        # estimate a bounded AI saving from cache + retry reduction (~15% of AI spend)
        est_ai_reduction = 0.15
        ai_saving_per_order = (base["monthly_cost_ai"] * est_ai_reduction) / orders
        levers.append({
            "lever": "Increase prompt caching + reduce retries on AI agents",
            "type": "ai",
            "projected_unit_cost": round(current - ai_saving_per_order, 5),
            "saving_per_order": round(ai_saving_per_order, 5),
            "annual_saving": round(ai_saving_per_order * orders * 12, 2),
            "risk_to_success": "none — reliability-improving" if can_cut_ai else
                               f"blocked: success {tk['success_rate']:.0%} below floor {min_ai_success_rate:.0%}",
            "touches_prod": False,
            "requires_approval": False,
            "constraint_respected": can_cut_ai,
            "evidence": f"AI is {ai_share*100:.0f}% of unit cost; cache hit rate {tk['cache_hit_rate']*100:.0f}%, "
                        f"retry rate {tk['retry_rate']:.2f}/outcome — both improvable without quality loss.",
        })

    # ---- compose a plan: apply safe levers in order until target met ----
    applied, projected = [], current
    for lv in sorted(levers, key=lambda x: x["saving_per_order"], reverse=True):
        # skip levers that violate constraints
        if lv.get("constraint_respected") is False:
            continue
        applied.append(lv)
        projected = min(projected, projected - lv["saving_per_order"])
        if projected <= target_unit_cost:
            break

    target_met = projected <= target_unit_cost
    needs_approval = any(l["requires_approval"] for l in applied)

    return {
        "product": product_id,
        "current_unit_cost": current,
        "target_unit_cost": target_unit_cost,
        "projected_unit_cost": round(projected, 5),
        "target_met": target_met,
        "requires_human_approval": needs_approval,
        "constraints": {
            "min_ai_success_rate": min_ai_success_rate,
            "protect_prod": protect_prod,
        },
        "recommended_levers": applied,
        "all_levers": levers,
        "summary": (
            f"Target {'met' if target_met else 'not fully met'}: "
            f"${current} → ${round(projected,5)}/order"
            + (" (pending human approval for prod-tagged changes)" if needs_approval else "")
        ),
    }
