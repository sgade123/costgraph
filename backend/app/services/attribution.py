"""
Attribution engine.

Turns the raw cost + telemetry planes into a Business Value Graph: for each
resource app1 touches, decide how much of that resource's cost belongs to app1,
by which method, with what evidence. Deterministic and auditable — every edge
records method, share, confidence, and a human-readable justification.

Attribution methods (schemas.AttributionMethod):
  dedicated          sole owner -> 100%
  consumption        shared compute (GKE) -> split by the allocation POLICY
                     (cpu_request | cpu_actual | memory | pod_count)
  message_attribute  shared Pub/Sub topic -> split by per-message source_app
  label / log        shared, fixed single signal (e.g. log lines)
  otel_baggage       cross-project service compute -> policy split * app1 call share
  call_share         (used within cross-project) app1's share of calls

The allocation policy governs COMPUTE only. Throughput/fixed resources use their
own single signal and do not change with the policy.
"""
from __future__ import annotations

from ..schemas import (
    CostRecord, TelemetryRecord, GraphNode, GraphEdge,
    NodeType, AttributionMethod,
)

# which telemetry attribute holds the share, per allocation policy
_POLICY_KEY = {
    "cpu_request": "cpu_request_share",
    "cpu_actual": "cpu_actual_share",
    "memory": "memory_share",
    "pod_count": "pod_share",
}

_POLICY_LABEL = {
    "cpu_request": "CPU request",
    "cpu_actual": "Actual CPU",
    "memory": "Memory",
    "pod_count": "Pod count",
}


def _tel_for(resource_id: str, telemetry: list[TelemetryRecord]) -> list[TelemetryRecord]:
    return [t for t in telemetry if t.resource_id == resource_id]


def _share_from_attr(records: list[TelemetryRecord], match: dict[str, str], key: str) -> float | None:
    """Read a percentage share (0..1) from the first telemetry record matching `match`."""
    for r in records:
        if all(r.attributes.get(k) == v for k, v in match.items()):
            raw = r.attributes.get(key)
            if raw is not None:
                return float(raw) / 100.0
    return None


def attribute(
    product_id: str,
    cost: list[CostRecord],
    telemetry: list[TelemetryRecord],
    policy: str = "cpu_request",
    dataflow_gain: float = 0.0,
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Return (nodes, edges) of the Business Value Graph for `product_id`.

    Each edge's attribution_share is the fraction of the target resource's cost
    attributed to the product, under the given allocation policy.
    """
    policy_key = _POLICY_KEY.get(policy, "cpu_request_share")
    policy_label = _POLICY_LABEL.get(policy, "CPU request")

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    # product (business unit) root node
    nodes.append(GraphNode(
        id=product_id, type=NodeType.PRODUCT, name=product_id, prod_tagged=True,
    ))

    for c in cost:
        labels = c.labels or {}
        rid = c.resource_id
        is_cross = labels.get("cross_project") == "true"
        is_shared = labels.get("shared") == "true"
        is_ai = c.provider in ("openai", "anthropic", "google") and c.service in ("OpenAI",)
        prod_tagged = labels.get("env") == "prod"
        tels = _tel_for(rid, telemetry)

        # --- classify + compute share -------------------------------------
        share: float
        method: AttributionMethod
        evidence: str
        attributed_by: str
        node_type = NodeType.RESOURCE

        if is_ai:
            # AI resources are attributed to the product they serve (label app==product)
            if labels.get("app") != product_id:
                continue
            share = 1.0
            method = AttributionMethod.DEDICATED
            evidence = f"AI spend tagged app={product_id}; attributed in full (tokenomics engine refines per-outcome)."
            attributed_by = "label: app"
            node_type = NodeType.AI_AGENT

        elif is_cross:
            # cross-project global service: compute split by policy, then app1 call share
            call_share = _share_from_attr(tels, {"product": product_id}, "call_share")
            if call_share is None:
                continue  # this product doesn't call the service
            if c.service == "GKE":
                pol = _share_from_attr(tels, {"product": product_id}, policy_key)
                pol = pol if pol is not None else 1.0
                share = pol * call_share
                method = AttributionMethod.OTEL_BAGGAGE
                evidence = (f"Cross-project service. Compute split by {policy_label} ({round(pol*100)}%) "
                            f"then app1 call-share via OTel baggage product={product_id} ({round(call_share*100)}%).")
                attributed_by = "OTel baggage: product"
                node_type = NodeType.SHARED_PLATFORM
            else:
                # cross-project logging etc: fixed by log share
                ls = _share_from_attr(tels, {"product": product_id}, "log_share")
                share = ls if ls is not None else call_share
                method = AttributionMethod.OTEL_BAGGAGE
                evidence = f"Cross-project support cost attributed by OTel baggage product={product_id} ({round(share*100)}%)."
                attributed_by = "OTel baggage: product"
                node_type = NodeType.SHARED_PLATFORM

        elif is_shared:
            if c.service == "GKE":
                s = _share_from_attr(tels, {"app": product_id}, policy_key)
                share = s if s is not None else 0.0
                method = AttributionMethod.CONSUMPTION
                evidence = f"Shared GKE cluster split by {policy_label}: app1 carries {round(share*100)}%."
                attributed_by = f"consumption: {policy_label}"
            elif c.service == "Pub/Sub":
                s = _share_from_attr(tels, {"source_app": product_id}, "message_share")
                share = s if s is not None else 0.0
                method = AttributionMethod.MESSAGE_ATTRIBUTE
                evidence = f"Shared topic split by per-message source_app={product_id}: {round(share*100)}%."
                attributed_by = "message attribute: source_app"
            elif c.service in ("Monitoring", "Logging + Monitoring"):
                s = _share_from_attr(tels, {"app": product_id}, "log_share")
                share = s if s is not None else 0.0
                method = AttributionMethod.LABEL
                evidence = f"Shared observability split by log volume label app={product_id}: {round(share*100)}%."
                attributed_by = "log label: app"
            else:
                s = _share_from_attr(tels, {"app": product_id}, policy_key)
                share = s if s is not None else 0.0
                method = AttributionMethod.CONSUMPTION
                evidence = f"Shared resource split by {policy_label}: {round(share*100)}%."
                attributed_by = f"consumption: {policy_label}"

        else:
            # dedicated resource: belongs to product if labeled so (or unlabeled default)
            if labels.get("app") not in (product_id, None):
                continue
            share = 1.0
            method = AttributionMethod.DEDICATED
            evidence = "Dedicated resource attributed in full by resource label."
            attributed_by = "label: app"

        if share <= 0:
            continue

        # apply an applied optimization (dataflow rightsizing) if present
        adj_cost = c.effective_cost
        if rid == "dataflow-app1" and dataflow_gain > 0:
            adj_cost *= (1 - dataflow_gain)

        nodes.append(GraphNode(
            id=rid, type=node_type, name=labels.get("agent") or labels.get("app") or labels.get("bucket") or c.service,
            project=c.account, prod_tagged=prod_tagged, monthly_cost=adj_cost,
            attributes={"service": c.service, **labels},
        ))
        edges.append(GraphEdge(
            source=product_id, target=rid, method=method,
            attribution_share=round(share, 4), confidence=1.0,
            evidence=evidence, attributed_by=attributed_by,
        ))

    return nodes, edges


def attributed_costs(
    product_id: str, cost: list[CostRecord], telemetry: list[TelemetryRecord],
    policy: str = "cpu_request", dataflow_gain: float = 0.0,
) -> list[dict]:
    """Convenience: per-resource attributed cost rows for the product."""
    nodes, edges = attribute(product_id, cost, telemetry, policy, dataflow_gain)
    node_by_id = {n.id: n for n in nodes}
    rows = []
    for e in edges:
        n = node_by_id[e.target]
        rows.append({
            "resource_id": e.target,
            "service": n.attributes.get("service", ""),
            "name": n.name,
            "project": n.project,
            "scope": "cross-project" if n.type == NodeType.SHARED_PLATFORM
                     else "ai" if n.type == NodeType.AI_AGENT else "in-project",
            "prod_tagged": n.prod_tagged,
            "method": e.method.value,
            "attributed_by": e.attributed_by,
            "share": e.attribution_share,
            "resource_cost": round(n.monthly_cost, 2),
            "attributed_cost": round(n.monthly_cost * e.attribution_share, 2),
            "evidence": e.evidence,
        })
    return rows
