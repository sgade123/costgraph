"""
CostGraph — normalized data-plane schemas.

These four record types are the contract every connector normalizes *into*.
A provider-specific connector (GCP billing, Datadog, OpenAI usage, an orders DB)
is responsible for mapping its raw format onto these shapes. Everything above
the connector layer — attribution, unit economics, tokenomics, RCA — operates
only on these normalized records and never on provider-specific formats.

This is what makes CostGraph adoptable: to onboard your own data you implement
one connector that emits these records; you do not touch the engines.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# --------------------------------------------------------------------------- #
#  4.1  Cost plane                                                            #
# --------------------------------------------------------------------------- #
class CostRecord(BaseModel):
    """One normalized cost line item. FOCUS-compatible field naming where practical.

    A cost connector (GCP billing export, AWS CUR, Datadog billing, an AI
    provider invoice) normalizes its rows into a stream of these.
    """
    timestamp: str = Field(..., description="ISO 8601 period start for this cost")
    provider: str = Field(..., description="gcp | aws | azure | openai | datadog | ...")
    billing_account: Optional[str] = None
    account: Optional[str] = Field(None, description="project / subscription / account id")
    service: str = Field(..., description="e.g. GKE, Pub/Sub, Cloud SQL, OpenAI")
    sku: Optional[str] = None
    resource_id: str = Field(..., description="stable id this cost is billed against")
    consumed_quantity: Optional[float] = None
    consumed_unit: Optional[str] = None
    effective_cost: float = Field(..., description="the money — amortized/effective cost")
    currency: str = "USD"
    region: Optional[str] = None
    tags: dict[str, str] = Field(default_factory=dict)
    labels: dict[str, str] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
#  4.2  Telemetry plane                                                       #
# --------------------------------------------------------------------------- #
class TelemetryRecord(BaseModel):
    """One normalized consumption signal — *who consumed how much*.

    This is the evidence used to split shared cost. Consumption is attributed
    to a product/tenant by an identity key that lives in `attributes`
    (a resource label, a namespace, or a propagated request attribute such as
    OpenTelemetry baggage `product`).
    """
    timestamp: str
    service_namespace: Optional[str] = None
    service_name: str
    service_instance: Optional[str] = None
    resource_id: str = Field(..., description="joins to CostRecord.resource_id")
    resource_type: Optional[str] = None

    # consumption measures (any subset may be present)
    cpu_seconds: Optional[float] = None
    memory_gb_seconds: Optional[float] = None
    storage_bytes: Optional[float] = None
    network_bytes: Optional[float] = None
    request_count: Optional[float] = None
    duration_ms: Optional[float] = None
    io_reads: Optional[float] = None
    io_writes: Optional[float] = None
    message_count: Optional[float] = None
    message_bytes: Optional[float] = None

    # trace context — lets us attribute across service / project boundaries
    trace_id: Optional[str] = None
    span_id: Optional[str] = None
    parent_span_id: Optional[str] = None

    # identity keys used for attribution (e.g. {"product": "app1"} from OTel baggage,
    # or {"app": "app1"} from a k8s label). The attribution engine groups by these.
    attributes: dict[str, str] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
#  4.3  Business-value plane  (the denominator)                              #
# --------------------------------------------------------------------------- #
class BusinessMetric(BaseModel):
    """The business denominator: how many units of value were produced.

    `unit_type` is configurable and never hard-coded to a single use case —
    completed_order, transaction, api_request, successful_ai_decision,
    records_processed, customer, inference, agent_workflow, ...
    """
    timestamp: str
    product_id: str
    unit_type: str = Field(..., description="the business unit being counted")
    unit_count: float
    customer_id: Optional[str] = None
    tenant_id: Optional[str] = None
    attributes: dict[str, str] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
#  4.4  AI tokenomics plane                                                   #
# --------------------------------------------------------------------------- #
class AIUsageEvent(BaseModel):
    """One AI/LLM invocation, normalized. This plane is what lets CostGraph
    answer *cost per successful AI outcome* — not just cost per token.

    An AI connector (OpenAI usage export, Anthropic, a self-hosted gateway)
    normalizes its usage rows into these.
    """
    # 'model_version' / 'model_calls' are legitimate AI-domain fields; opt out of
    # Pydantic's reserved 'model_' namespace so they don't trigger warnings.
    model_config = {"protected_namespaces": ()}

    timestamp: str
    provider: str = Field(..., description="openai | anthropic | google | self-hosted | ...")
    model: str
    model_version: Optional[str] = None
    agent_name: Optional[str] = None
    workflow_name: Optional[str] = None

    # token accounting
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0

    # call-shape overhead
    tool_calls: int = 0
    model_calls: int = 1
    retry_count: int = 0
    latency_ms: Optional[float] = None

    # cost
    input_cost: float = 0.0
    output_cost: float = 0.0
    total_ai_cost: float = 0.0

    # linkage + outcome — the keys that make "cost per successful outcome" possible
    trace_id: Optional[str] = None
    transaction_id: Optional[str] = None
    business_unit_id: Optional[str] = Field(None, description="which product/outcome this served")
    quality_score: Optional[float] = Field(None, description="0..1 outcome quality if scored")
    success: Optional[bool] = Field(None, description="did this AI invocation succeed?")


# --------------------------------------------------------------------------- #
#  Value-graph node types (section 5 of the blueprint)                        #
# --------------------------------------------------------------------------- #
class NodeType(str, Enum):
    BUSINESS_UNIT = "BUSINESS_UNIT"
    PRODUCT = "PRODUCT"
    SERVICE = "SERVICE"
    WORKLOAD = "WORKLOAD"
    RESOURCE = "RESOURCE"
    EXECUTION = "EXECUTION"
    SHARED_PLATFORM = "SHARED_PLATFORM"
    AI_AGENT = "AI_AGENT"
    AI_MODEL = "AI_MODEL"
    DATA_SERVICE = "DATA_SERVICE"
    CLOUD_ACCOUNT = "CLOUD_ACCOUNT"
    KUBERNETES_CLUSTER = "KUBERNETES_CLUSTER"


class AttributionMethod(str, Enum):
    """How a node's cost is attributed to a product. This is auditable — every
    attributed edge records which method and which evidence produced its share."""
    DEDICATED = "dedicated"            # 100%, sole owner
    LABEL = "label"                    # grouped by a resource label / namespace
    OTEL_BAGGAGE = "otel_baggage"      # grouped by propagated request attribute (cross-project)
    CONSUMPTION = "consumption"        # split by a telemetry measure (cpu/mem/requests/...)
    MESSAGE_ATTRIBUTE = "message_attribute"  # shared topic split by per-message attribute
    CALL_SHARE = "call_share"          # downstream service split by share of calls


class GraphNode(BaseModel):
    id: str
    type: NodeType
    name: str
    project: Optional[str] = None
    prod_tagged: bool = False
    monthly_cost: float = 0.0          # this node's own (unattributed) monthly cost
    attributes: dict[str, str] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    """A directed relationship product<-...-resource with an auditable attribution share."""
    source: str                        # upstream (e.g. product / business unit)
    target: str                        # downstream (resource / service / execution)
    method: AttributionMethod
    attribution_share: float = Field(..., ge=0.0, le=1.0)
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    evidence: str = Field("", description="human-readable justification for the share")
    attributed_by: str = Field("", description="the key/measure the split is grouped by")
