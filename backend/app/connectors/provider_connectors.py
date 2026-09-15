"""
Provider connectors — real + reference implementations.

This module contains:
  * OpenAIUsageConnector  — a REAL, working connector that pulls your OpenAI
    usage via the API and normalizes it into AIUsageEvent. Needs OPENAI_API_KEY.
  * GcpCostConnector       — REFERENCE implementation showing exactly how to pull
    GCP billing-export rows from BigQuery and map to CostRecord. Credential-gated.
  * DatadogTelemetryConnector — REFERENCE implementation for consumption metrics.

The reference connectors show the real integration shape. They are gated so the
repo runs without cloud credentials; wire them in config once you have creds.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

from .base import CostConnector, TelemetryConnector, AIUsageConnector
from ..schemas import CostRecord, TelemetryRecord, AIUsageEvent


# ===========================================================================
#  REAL: OpenAI usage connector
# ===========================================================================
class OpenAIUsageConnector(AIUsageConnector):
    """Pulls AI usage from the OpenAI usage API and normalizes to AIUsageEvent.

    Config:
        connector: openai_usage
        source: ""                      # unused; auth via OPENAI_API_KEY env
    Requires: OPENAI_API_KEY in the environment.

    Note: OpenAI's usage/costs API returns aggregate buckets, not per-invocation
    quality/success (those are app-level signals only you can emit). This
    connector fills token/cost/model from OpenAI and leaves quality_score/success
    to be enriched from your own outcome log (see enrich_with_outcomes()).
    """
    name = "openai_usage"

    def __init__(self, source: str = "", days: int = 30):
        self.days = days

    def fetch(self) -> list[AIUsageEvent]:
        key = os.getenv("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OpenAIUsageConnector needs OPENAI_API_KEY. "
                "Set it, or use the file connector for offline/demo runs."
            )
        import httpx
        # OpenAI Usage API (completions usage buckets). See:
        # https://platform.openai.com/docs/api-reference/usage
        # NOTE: /organization/usage/* requires an ADMIN API key, not a regular
        # project/secret key. A normal sk-... key returns 403 here.
        start = int((datetime.now(timezone.utc).timestamp())) - self.days * 86400
        events: list[AIUsageEvent] = []
        try:
            with httpx.Client(timeout=30) as c:
                r = c.get(
                    "https://api.openai.com/v1/organization/usage/completions",
                    headers={"Authorization": f"Bearer {key}"},
                    params={"start_time": start, "bucket_width": "1d", "group_by": ["model"], "limit": 31},
                )
                r.raise_for_status()
                data = r.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403):
                raise RuntimeError(
                    "OpenAI usage API returned "
                    f"{e.response.status_code}: this endpoint requires an ADMIN API key "
                    "(Settings → Organization → Admin keys), not a regular project key. "
                    "Create an admin key and set OPENAI_API_KEY to it, or use the file "
                    "connector for demo runs. (This permission friction is exactly why "
                    "AI cost attribution is hard — see docs/CONNECTORS.md.)"
                ) from e
            raise
        for bucket in data.get("data", []):
            ts = datetime.fromtimestamp(bucket.get("start_time", start), tz=timezone.utc).isoformat()
            for result in bucket.get("results", []):
                    model = result.get("model", "unknown")
                    in_tok = int(result.get("input_tokens", 0) or 0)
                    out_tok = int(result.get("output_tokens", 0) or 0)
                    cached = int(result.get("input_cached_tokens", 0) or 0)
                    n_req = int(result.get("num_model_requests", 1) or 1)
                    events.append(AIUsageEvent(
                        timestamp=ts,
                        provider="openai",
                        model=model,
                        input_tokens=in_tok,
                        output_tokens=out_tok,
                        cached_tokens=cached,
                        model_calls=n_req,
                        total_ai_cost=0.0,  # enrich from the costs API or a price map
                        # quality/success are app signals; enrich from your outcome log:
                        quality_score=None,
                        success=None,
                    ))
        return events

    @staticmethod
    def enrich_with_outcomes(events: list[AIUsageEvent], outcomes: dict[str, dict]) -> list[AIUsageEvent]:
        """Join OpenAI usage with your own per-outcome quality/success log
        (keyed by transaction_id). This is where cost-per-SUCCESSFUL-outcome
        becomes possible — OpenAI can't tell you if the outcome was good; only
        your application can."""
        for e in events:
            o = outcomes.get(e.transaction_id or "")
            if o:
                e.quality_score = o.get("quality_score")
                e.success = o.get("success")
                e.business_unit_id = o.get("business_unit_id")
        return events


# ===========================================================================
#  REFERENCE: GCP billing-export cost connector
# ===========================================================================
class GcpCostConnector(CostConnector):
    """REAL — pull SKU-level cost from a GCP Billing export in BigQuery.

    Prerequisites (one-time, in your GCP org):
      1. Enable Cloud Billing detailed export to BigQuery.
      2. Grant the service account BigQuery Data Viewer on the export dataset.
      3. Set GOOGLE_APPLICATION_CREDENTIALS to the service-account key
         (or run `gcloud auth application-default login` for local testing).

    Config:
        connector: gcp_cost
        source: "project.dataset.gcp_billing_export_resource_v1_XXXX"

    Needs `pip install google-cloud-bigquery`. If unavailable or the query fails,
    raises a clear RuntimeError so a caller can fall back to a CSV export
    (see GcpCsvCostConnector).
    """
    name = "gcp_cost"

    def __init__(self, source: str, days: int = 30):
        self.table = source
        self.days = days

    def fetch(self) -> list[CostRecord]:
        try:
            from google.cloud import bigquery  # type: ignore
        except ImportError as e:
            raise RuntimeError(
                "GcpCostConnector needs google-cloud-bigquery: "
                "`pip install google-cloud-bigquery`. Or export your billing to CSV "
                "and use gcp_csv_cost. See docs/CONNECTORS.md."
            ) from e

        try:
            client = bigquery.Client()
            query = f"""
                SELECT
                  usage_start_time            AS ts,
                  project.id                  AS account,
                  service.description         AS service,
                  sku.description             AS sku,
                  COALESCE(resource.name, sku.description) AS resource_id,
                  usage.amount                AS consumed_quantity,
                  usage.unit                  AS consumed_unit,
                  cost + IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c),0) AS effective_cost,
                  currency,
                  location.region             AS region,
                  billing_account_id          AS billing_account,
                  (SELECT ARRAY_AGG(STRUCT(l.key AS key, l.value AS value)) FROM UNNEST(labels) l) AS labels
                FROM `{self.table}`
                WHERE usage_start_time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL {self.days} DAY)
            """
            rows = list(client.query(query).result())
        except Exception as e:
            raise RuntimeError(
                f"GcpCostConnector query failed against '{self.table}': {e}. "
                "Check the table id, credentials (GOOGLE_APPLICATION_CREDENTIALS "
                "or `gcloud auth application-default login`), and BigQuery Data "
                "Viewer permission. You can fall back to a CSV export (gcp_csv_cost)."
            ) from e

        out: list[CostRecord] = []
        for row in rows:
            labels = {l["key"]: l["value"] for l in (row.get("labels") or [])}
            out.append(CostRecord(
                timestamp=str(row["ts"]), provider="gcp",
                billing_account=row.get("billing_account"), account=row.get("account"),
                service=row["service"] or "unknown", sku=row.get("sku"),
                resource_id=row["resource_id"] or (row["service"] or "unknown"),
                consumed_quantity=row.get("consumed_quantity"),
                consumed_unit=row.get("consumed_unit"),
                effective_cost=float(row["effective_cost"] or 0),
                currency=row.get("currency") or "USD", region=row.get("region"),
                labels=labels,
            ))
        return out


class GcpCsvCostConnector(CostConnector):
    """REAL fallback — load a GCP billing CSV export (downloaded from the Billing
    console → Reports → Download CSV, or a BigQuery export saved to CSV) and
    normalize to CostRecord. Zero cloud credentials needed.

    Config:
        connector: gcp_csv_cost
        source: app/data/gcp_billing_export.csv

    Column mapping is tolerant of the common GCP export headers; adjust
    _COLMAP below if your export differs.
    """
    name = "gcp_csv_cost"

    # map various GCP CSV header spellings -> our fields (case-insensitive, substring)
    _COLMAP = {
        "service": ["service description", "service", "service.description"],
        "sku": ["sku description", "sku", "sku.description"],
        "cost": ["subtotal ($)", "cost ($)", "subtotal", "cost", "effective_cost", "unrounded cost ($)"],
        "currency": ["currency", "currency code"],
        "project": ["project id", "project name", "project", "project.id"],
        "region": ["region", "location", "location/region", "location.region"],
    }

    def __init__(self, source: str):
        self.path = source

    def _find_col(self, headers: list[str], key: str) -> str | None:
        """Case-insensitive substring match against known header spellings."""
        low = {h.lower().strip(): h for h in headers}
        for want in self._COLMAP[key]:
            # exact (case-insensitive)
            if want in low:
                return low[want]
        for want in self._COLMAP[key]:
            # substring fallback
            for hl, orig in low.items():
                if want in hl:
                    return orig
        return None

    def fetch(self) -> list[CostRecord]:
        import csv
        from pathlib import Path
        p = Path(self.path)
        if not p.exists():
            raise RuntimeError(f"GcpCsvCostConnector: file not found: {self.path}")

        # GCP exports sometimes have preamble lines before the header row.
        # Find the first line that looks like a header (contains 'Service' or 'Cost').
        raw = p.read_text().splitlines()
        header_idx = 0
        for i, line in enumerate(raw[:10]):
            ll = line.lower()
            if ("service" in ll or "sku" in ll) and ("cost" in ll or "subtotal" in ll):
                header_idx = i
                break
        reader = csv.DictReader(raw[header_idx:])
        headers = reader.fieldnames or []
        c_cost = self._find_col(headers, "cost")
        c_svc = self._find_col(headers, "service")
        if not c_cost:
            raise RuntimeError(
                f"GcpCsvCostConnector: couldn't find a cost column in {headers}. "
                "Expected something like 'Cost ($)' or 'Subtotal ($)'. "
                "Add your header to _COLMAP['cost']."
            )
        c_sku = self._find_col(headers, "sku")
        c_cur = self._find_col(headers, "currency")
        c_proj = self._find_col(headers, "project")
        c_reg = self._find_col(headers, "region")

        out: list[CostRecord] = []
        for row in reader:
            raw_cost = (row.get(c_cost) or "").replace("$", "").replace(",", "").strip()
            if not raw_cost:
                continue
            try:
                cost = float(raw_cost)
            except ValueError:
                continue
            svc = (row.get(c_svc) if c_svc else None) or "unknown"
            out.append(CostRecord(
                timestamp="2026-08-01T00:00:00Z", provider="gcp",
                account=row.get(c_proj) if c_proj else None,
                service=svc, sku=row.get(c_sku) if c_sku else None,
                resource_id=svc,  # CSV export lacks resource_id; group by service
                effective_cost=cost,
                currency=(row.get(c_cur) if c_cur else None) or "USD",
                region=row.get(c_reg) if c_reg else None,
                labels={},
            ))
        return out


# ===========================================================================
#  REFERENCE: Datadog telemetry connector
# ===========================================================================
class DatadogTelemetryConnector(TelemetryConnector):
    """REFERENCE — pull consumption metrics from Datadog and normalize to
    TelemetryRecord. Shows how to map a metric query into the split-evidence
    the attribution engine needs.

    Config:
        connector: datadog_telemetry
        source: "avg:kubernetes.cpu.usage.total{*} by {kube_namespace,app}"
    Requires: DD_API_KEY and DD_APP_KEY in the environment.
    """
    name = "datadog_telemetry"

    def __init__(self, source: str):
        self.query = source

    def fetch(self) -> list[TelemetryRecord]:
        api_key = os.getenv("DD_API_KEY"); app_key = os.getenv("DD_APP_KEY")
        if not (api_key and app_key):
            raise RuntimeError(
                "DatadogTelemetryConnector needs DD_API_KEY and DD_APP_KEY. "
                "See docs/CONNECTORS.md. Use the file connector for demo runs."
            )
        import time
        import httpx
        now = int(time.time())
        with httpx.Client(timeout=30) as c:
            r = c.get(
                "https://api.datadoghq.com/api/v1/query",
                headers={"DD-API-KEY": api_key, "DD-APPLICATION-KEY": app_key},
                params={"from": now - 30 * 86400, "to": now, "query": self.query},
            )
            r.raise_for_status()
            series = r.json().get("series", [])
        out: list[TelemetryRecord] = []
        for s in series:
            scope = dict(tag.split(":", 1) for tag in s.get("tag_set", []) if ":" in tag)
            total = sum(p[1] for p in s.get("pointlist", []) if p[1] is not None)
            out.append(TelemetryRecord(
                timestamp=datetime.fromtimestamp(now, tz=timezone.utc).isoformat(),
                service_name=scope.get("app", s.get("scope", "unknown")),
                resource_id=scope.get("app", "unknown"),
                cpu_seconds=total,
                attributes={"app": scope.get("app", ""), "namespace": scope.get("kube_namespace", "")},
            ))
        return out
