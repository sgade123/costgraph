# CostGraph

**Open-source business-flow cost attribution for cloud and AI.**

> Built for the AI Builders Hackathon. Point it at your billing and telemetry, define your business unit, and CostGraph maps how your product actually runs — then tells you what one business outcome costs, including its AI cost per successful outcome.

CostGraph answers the question cloud bills dodge: **what does one business outcome actually cost?** — one completed order, one API request, one successful AI decision — across shared infrastructure, asynchronous messaging, ephemeral jobs, cross-project downstream services, and AI/LLM workloads.

The story is **KNOW → EXPLAIN → OPTIMIZE**: know what one outcome costs, explain why it changed and how each cost was attributed, and simulate optimizations to hit a target unit cost without breaking service-level or AI-quality constraints.

---

## Why CostGraph is adoptable, not just a demo

The design is **schema-first and connector-based**, so onboarding your own data means editing config and implementing one connector — never touching the engines.

- **Four normalized data planes** (`backend/app/schemas.py`): Cost, Telemetry, Business, and AI Usage. Every connector normalizes a provider's raw format *into* these; every engine reads *only* these.
- **Connector contract** (`backend/app/connectors/base.py`): implement `fetch()` for the plane you have. A complete, working **file connector** (`file_connectors.py`) ships as the reference — export your data to JSON/CSV and CostGraph runs on it with zero code changes.
- **Config-driven** (`backend/app/config/costgraph.yaml`): declare your product, business unit, allocation policy, guardrails, and which connector feeds each plane.

```
provider raw data ──▶ connector ──▶ normalized record ──▶ repository ──▶ engines
   (GCP/AWS/OTel/          (you            (canonical         (loads all       (attribution,
    OpenAI/orders DB)       write)          schema)            planes)          economics, tokenomics,
                                                                                RCA, optimization)
```

To onboard your data: **export billing/telemetry/business/AI-usage to files** (see [docs/CONNECTORS.md](docs/CONNECTORS.md)), point `costgraph.yaml` at them, and run — works today with zero credentials. **Real, working connectors today:** GCP billing via CSV export (`gcp_csv_cost`), GCP billing via BigQuery export (`gcp_cost`), and OpenAI usage (`openai_usage`). A Datadog telemetry connector ships as a credential-gated reference showing the integration shape. AWS, Azure, and additional live connectors are on the roadmap — the architecture is cloud-agnostic and the extension path is real and documented today.

---

## Status

This is an active, milestone-based build.

**Built (Milestone 1 — foundation):**
- Repo structure, Apache-2.0 license
- Four normalized data-plane schemas + value-graph node/edge model
- Connector contract, connector registry, working file connector
- Config loader + config-driven onboarding
- Repository that loads all four planes through connectors
- Seeded App1 demo dataset across all four planes (in-project + cross-project + AI usage)

**Built (Milestone 2 — engines):**
- Attribution engine — six methods (dedicated, consumption/policy, message-attribute, label, OTel baggage, call-share); builds the Business Value Graph with auditable evidence per edge
- Unit economics engine — fully-loaded cost per outcome, decomposed into in-project / cross-project / AI
- AI tokenomics engine — cost per *successful* outcome, retry/tool-call/cache overhead, model mix, optimization levers
- RCA (period-over-period compare) + FastAPI app exposing it all
- Engine test suite

**Built (Milestone 3 — constrained optimization):**
- Optimization engine — given a target unit cost + constraints, returns ranked deterministic levers with projected savings
- **Guardrail enforcement** — prod-tagged changes are flagged `requires_approval`; the agent proposes, the human governs
- **Constraint enforcement** — AI cost-cutting levers are blocked when they would drop AI success below the floor
- `POST /api/optimize/{product}` endpoint

**Built (Milestone 4 — dashboard):**
- React + Vite + Tailwind dashboard: hero with in-project/cross-project/AI decomposition, allocation-policy toggle, cost breakdown with click-to-reveal evidence, cross-project panel, tokenomics, optimization simulator, RCA

**Built (Milestone 5 — agentic layer):**
- Multi-step **agentic workflow trace** (fraud-triage → payments → support), with per-step cost, retries, success, and cost-per-successful-outcome + cost-of-failures rollup
- **AI agent** (`POST /api/agent/{product}`) — natural-language question → calls the real engines → grounded answer. Uses OpenAI if `OPENAI_API_KEY` is set, else a deterministic intent-routing fallback (demo always works). Every answer includes a `tool_trace` proving which engines it called.
- Dashboard: agent chat panel (with "how I got this" tool trace) + agentic-workflow-trace view
- 11 passing tests

**Next:**
- Deploy (Render/Vercel), demo video, final naming, submission

### The "agents all the way down" story
An AI agent you talk to, that measures the cost of *your* AI agents, and proves its work by showing the deterministic engine calls behind every answer.

---

## Run it

**Requires Python 3.10–3.12** (Pydantic v2 has no prebuilt wheel for 3.13/3.14 yet).

```bash
cd backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# optional: for the GCP BigQuery connector, also:
#   pip install -r requirements-connectors.txt

# run the engine tests
python -m pytest tests/ -q

# start the API
uvicorn app.main:app --reload            # http://localhost:8000
```

Then hit the endpoints:

```bash
curl localhost:8000/health
curl "localhost:8000/api/economics/app1"                    # cost per order (cpu_request)
curl "localhost:8000/api/economics/app1?policy=cpu_actual"  # allocation swing
curl "localhost:8000/api/economics/app1/compare"            # period-over-period RCA
curl "localhost:8000/api/tokenomics/app1"                   # AI cost per successful outcome
curl "localhost:8000/api/graph/app1"                        # Business Value Graph
curl -X POST "localhost:8000/api/optimize/app1" -H "Content-Type: application/json" \
     -d '{"target_unit_cost":0.070}'                       # constrained optimization
```

---

## Design principle: deterministic core, AI on top

All financial math — attribution, unit cost, RCA, optimization — is **deterministic** and auditable. The LLM agent only interprets intent, orchestrates the deterministic engines, and explains results in plain language. This separation is what makes the numbers trustworthy and the demo repeatable.

## License

Apache 2.0 — see [LICENSE](./LICENSE).
