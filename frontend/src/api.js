// Thin client over the CostGraph FastAPI backend. In dev, Vite proxies
// /api and /health to http://localhost:8000 (see vite.config.js). In prod,
// set VITE_API_BASE to the deployed API origin.
const BASE = import.meta.env.VITE_API_BASE || ''

async function get(path) {
  const r = await fetch(`${BASE}${path}`)
  if (!r.ok) throw new Error(`${path} → ${r.status}`)
  return r.json()
}
async function post(path, body) {
  const r = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!r.ok) throw new Error(`${path} → ${r.status}`)
  return r.json()
}

export const api = {
  health: () => get('/health'),
  economics: (product, policy) => get(`/api/economics/${product}?policy=${policy}`),
  compare: (product, policy) => get(`/api/economics/${product}/compare?policy=${policy}`),
  graph: (product, policy) => get(`/api/graph/${product}?policy=${policy}`),
  tokenomics: (product) => get(`/api/tokenomics/${product}`),
  optimize: (product, body) => post(`/api/optimize/${product}`, body),
  workflow: (product) => get(`/api/workflow/${product}`),
  agent: (product, body) => post(`/api/agent/${product}`, body),
}
