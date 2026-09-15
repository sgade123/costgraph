# Connecting your own data

CostGraph runs on four normalized data planes (see `backend/app/schemas.py`).
A **connector** maps one provider's raw data into those normalized records.
Everything above the connector — attribution, unit economics, tokenomics,
optimization, the agent — is provider-agnostic and never changes.

## Adoption paths, from fastest to most integrated

### 1. File connector (works today, zero credentials)
Export your data to JSON/CSV in the shapes below, point `config/costgraph.yaml`
at the files, and run. This is the fastest way to run CostGraph on YOUR numbers.

- **Cost** → JSON array of `CostRecord` (see `app/data/cost_records.json`)
- **Telemetry** → JSON array of `TelemetryRecord` (see `app/data/telemetry.json`)
- **Business** → CSV: `timestamp,product_id,unit_type,unit_count,customer_id,tenant_id`
- **AI usage** → JSON array of `AIUsageEvent` (see `app/data/ai_usage.json`)

### 2. Real provider connectors
Implemented in `app/connectors/provider_connectors.py`:

| Connector | Status | Needs | Source in config |
|---|---|---|---|
| `openai_usage` | **working** | `OPENAI_API_KEY` | `""` (auth via env) |
| `gcp_cost` | **working** | `google-cloud-bigquery` (`pip install -r requirements-connectors.txt`) + GCP creds | billing-export table id |
| `gcp_csv_cost` | **working** | none (downloaded billing CSV) | path to CSV |
| `datadog_telemetry` | reference | `DD_API_KEY`, `DD_APP_KEY` | a Datadog metric query |

"Reference" means the real query/mapping code is there and correct, but is
credential-gated so the repo runs offline. Wire it in config once you have creds.

## Test with your real OpenAI usage (the working connector)

```bash
cd backend && source .venv/bin/activate
export OPENAI_API_KEY=sk-...          # your key

# quick standalone test — pull real usage and print it
python -c "import sys; sys.path.insert(0,'.'); \
from app.connectors.provider_connectors import OpenAIUsageConnector as O; \
ev=O(days=30).fetch(); print('pulled', len(ev), 'usage buckets from OpenAI'); \
print(ev[0].model, ev[0].input_tokens, 'in /', ev[0].output_tokens, 'out') if ev else print('no usage in window')"
```

To run the whole app on your OpenAI data, set the ai_usage plane in
`config/costgraph.yaml`:

```yaml
planes:
  ai_usage:
    connector: openai_usage
    source: ""
```

Then `uvicorn app.main:app --reload` and hit `/api/tokenomics/app1`.

> Note: OpenAI's usage API returns tokens/model/cost per bucket, but **not**
> per-outcome quality or success — those are application signals only you can
> emit. `OpenAIUsageConnector.enrich_with_outcomes()` shows how to join usage
> with your own outcome log (keyed by transaction_id) to get true
> cost-per-successful-outcome.

## Write your own connector

1. Subclass the right base in `app/connectors/base.py` and implement `fetch()`:

```python
from .base import CostConnector
from ..schemas import CostRecord

class MyCloudCostConnector(CostConnector):
    name = "mycloud_cost"
    def __init__(self, source: str):
        self.source = source
    def fetch(self) -> list[CostRecord]:
        rows = my_billing_api(self.source)
        return [CostRecord(
            timestamp=r["date"], provider="mycloud", service=r["service"],
            resource_id=r["resource"], effective_cost=float(r["cost"]),
            labels=r.get("labels", {}),
        ) for r in rows]
```

2. Register it in `app/connectors/registry.py`.
3. Reference it in `config/costgraph.yaml`.

That's it — the engines pick it up with no other changes.

## The honest note on "real-time"

Cloud cost is not real-time: billing exports land **daily**. The correct
production pattern is a scheduled job that runs connectors on a cadence
(daily/hourly), writes normalized records to a store, and serves the latest
rollup. CostGraph's design fits this — connectors pull; engines read the result.
