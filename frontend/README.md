# CostGraph — Frontend

React + Vite + Tailwind dashboard for CostGraph. Talks to the FastAPI
backend (see ../backend).

## Run (dev)

```bash
# 1. start the backend first (in ../backend):
#    uvicorn app.main:app --reload         # http://localhost:8000

# 2. then the frontend:
npm install
npm run dev                                 # http://localhost:5173
```

Vite proxies `/api` and `/health` to `http://localhost:8000` in dev
(see vite.config.js). For a deployed build, set `VITE_API_BASE` to the
deployed API origin.

## Build

```bash
npm run build          # outputs to dist/
npm run preview        # preview the production build
```

## Sections

- **Hero** — fully-loaded cost per order, decomposed into in-project / cross-project / AI
- **Allocation policy** — switch CPU-request / actual / memory / pods; everything recomputes live
- **Cost breakdown** — every resource with attribution method, share, and (click a row) its evidence
- **Cross-project flow** — global services attributed by OTel baggage
- **AI tokenomics** — cost per successful outcome, cache/retry/tool overhead, model mix
- **Optimization simulator** — target a unit cost under an AI-success floor; guardrail-gated levers flagged for approval
- **RCA** — why unit cost changed period-over-period

## Agent

The "Ask the agent" panel calls `POST /api/agent/{product}`. The backend uses an
LLM if `OPENAI_API_KEY` is set, otherwise deterministic intent routing — either
way it calls the real engines and returns a `tool_trace` you can expand under
each answer ("how I got this").
