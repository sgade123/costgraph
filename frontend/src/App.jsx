import { useState, useEffect, useCallback } from 'react'
import { api } from './api'
import CostFlowGraph from './CostFlowGraph'

const POLICIES = [
  { key: 'cpu_request', label: 'CPU request', blurb: 'Split shared compute by requested vCPU — the billing-default view. Governs your GKE cluster AND downstream global services.' },
  { key: 'cpu_actual', label: 'Actual CPU', blurb: 'Split by measured vCPU used. Rewards efficiency across your cluster and every downstream service; shifts cost to the noisy neighbor.' },
  { key: 'memory', label: 'Memory', blurb: 'Split by memory footprint. Fair for memory-bound workloads.' },
  { key: 'pod_count', label: 'Pod count', blurb: 'Split evenly by pod. Simple, coarse, over-charges lightweight services.' },
]

const usd = (n) => '$' + (n ?? 0).toLocaleString('en-US', { maximumFractionDigits: 0 })
const unit = (n) => '$' + (n ?? 0).toFixed(4)
const svcColor = (s) => ({
  GKE: '#60a5fa', 'Pub/Sub': '#fbbf24', Dataflow: '#a78bfa', 'Cloud SQL': '#4ade80',
  Firestore: '#f472b6', Storage: '#38bdf8', Monitoring: '#94a3b8', OpenAI: '#c4a5ff',
}[s] || '#94a3b8')

export default function App() {
  const [product] = useState('app1')
  const [policy, setPolicy] = useState('cpu_request')
  const [view, setView] = useState('dashboard')  // 'dashboard' | 'flow'
  const [econ, setEcon] = useState(null)
  const [comp, setComp] = useState(null)
  const [tok, setTok] = useState(null)
  const [wf, setWf] = useState(null)
  const [health, setHealth] = useState(null)
  const [err, setErr] = useState(null)
  const [flash, setFlash] = useState(0)

  // agent state
  const [messages, setMessages] = useState([])
  const [question, setQuestion] = useState('')
  const [agentLoading, setAgentLoading] = useState(false)

  // optimizer state
  const [target, setTarget] = useState(0.070)
  const [minSuccess, setMinSuccess] = useState(0.95)
  const [protectProd, setProtectProd] = useState(true)
  const [optResult, setOptResult] = useState(null)
  const [optLoading, setOptLoading] = useState(false)

  const load = useCallback(async (pol) => {
    try {
      setErr(null)
      const [e, c, t, w, h] = await Promise.all([
        api.economics(product, pol), api.compare(product, pol),
        api.tokenomics(product), api.workflow(product), api.health(),
      ])
      setEcon(e); setComp(c); setTok(t); setWf(w); setHealth(h); setFlash((f) => f + 1)
    } catch (ex) { setErr(ex.message) }
  }, [product])

  useEffect(() => { load(policy) }, [policy, load])

  const askAgent = async (q) => {
    const text = (q ?? question).trim()
    if (!text) return
    setMessages((m) => [...m, { role: 'user', text }])
    setQuestion(''); setAgentLoading(true)
    try {
      const res = await api.agent(product, { question: text, policy })
      setMessages((m) => [...m, { role: 'agent', text: res.answer, trace: res.tool_trace, mode: res.mode }])
    } catch (ex) {
      setMessages((m) => [...m, { role: 'agent', text: 'Error: ' + ex.message }])
    } finally { setAgentLoading(false) }
  }

  const runOptimize = async () => {
    setOptLoading(true)
    try {
      const res = await api.optimize(product, {
        target_unit_cost: Number(target), policy,
        min_ai_success_rate: Number(minSuccess), protect_prod: protectProd,
      })
      setOptResult(res)
    } catch (ex) { setErr(ex.message) } finally { setOptLoading(false) }
  }

  if (err) return <Shell><div className="p-6 mono text-[13px]" style={{ color: 'var(--red)' }}>
    Error: {err}<br /><span style={{ color: 'var(--ink-dim)' }}>Is the backend running on :8000? Start it with <code>uvicorn app.main:app --reload</code></span>
  </div></Shell>
  if (!econ) return <Shell><div className="p-6 mono text-[13px]" style={{ color: 'var(--ink-dim)' }}>Loading CostGraph…</div></Shell>

  const rows = econ.breakdown || []
  const inProj = rows.filter((r) => r.scope === 'in-project')
  const cross = rows.filter((r) => r.scope === 'cross-project')
  const ai = rows.filter((r) => r.scope === 'ai')
  const maxCost = Math.max(...rows.map((r) => r.attributed_cost), 1)
  const deltaUp = (comp?.change_pct ?? 0) > 0

  return (
    <Shell health={health} view={view} setView={setView}>
      {view === 'flow' ? (
        <div className="p-5 space-y-4">
          <div className="text-[13px] leading-relaxed px-1" style={{ color: 'var(--ink-dim)' }}>
            The <span style={{ color: 'var(--acc)' }}>cost graph</span> for {product}: how one product's cost flows
            through shared infrastructure, cross-project services, and AI. Node size is attributed cost; drag to explore.
          </div>
          <CostFlowGraph product={product} policy={policy} />
          <div className="rounded-lg border p-4 text-[12px]" style={{ borderColor: 'var(--line)', background: 'var(--panel)', color: 'var(--ink-dim)' }}>
            Every edge is an attributed cost with a method: <span className="mono" style={{color:'var(--blue)'}}>by policy</span> (shared compute),
            <span className="mono" style={{color:'var(--amber)'}}> by messages</span> (Pub/Sub),
            <span className="mono" style={{color:'var(--purple)'}}> OTel baggage</span> (cross-project), or <span className="mono">dedicated</span>.
            Switch to Dashboard for the full breakdown, tokenomics, and the agent.
          </div>
        </div>
      ) : (
      <div className="grid" style={{ gridTemplateColumns: 'minmax(0,1fr) 360px', gap: 0 }}>
        {/* ============ MAIN COLUMN ============ */}
        <main className="p-5 space-y-4" style={{ minWidth: 0 }}>
          {/* one-liner */}
          <div className="text-[13px] leading-relaxed px-1" style={{ color: 'var(--ink-dim)' }}>
            We built CostGraph to answer what our cloud bills never could: the true cost of one
            <span style={{ color: 'var(--acc)' }}> business outcome</span> — across shared infrastructure,
            cross-project services, and AI, with the human setting how cost is split.
          </div>

          {/* HERO */}
          <section key={flash} className="flash rounded-lg border p-5" style={{ borderColor: 'var(--line)', background: 'linear-gradient(180deg,var(--panel-2),var(--panel))' }}>
            <div className="flex items-end justify-between flex-wrap gap-4">
              <div>
                <div className="text-[12px] mb-1" style={{ color: 'var(--ink-dim)' }}>Cost per completed order</div>
                <div className="mono font-semibold tabnum" style={{ fontSize: 52, lineHeight: 1, color: 'var(--acc)' }}>{unit(econ.cost_per_order)}</div>
                {comp && <div className="text-[12px] mt-2 flex items-center gap-2" style={{ color: 'var(--ink-dim)' }}>
                  <span className="mono tabnum" style={{ color: deltaUp ? 'var(--red)' : 'var(--acc)' }}>{deltaUp ? '▲' : '▼'} {Math.abs(comp.change_pct)}%</span>
                  <span>vs last month ({unit(comp.previous_cost_per_order)})</span>
                </div>}
              </div>
              <div className="text-right space-y-1">
                <div className="text-[12px]" style={{ color: 'var(--ink-faint)' }}>attributed to {product} / month</div>
                <div className="mono font-semibold tabnum text-[22px]">{usd(econ.monthly_cost_total)}</div>
                <div className="text-[12px] mono tabnum" style={{ color: 'var(--ink-faint)' }}>{econ.completed_orders.toLocaleString()} orders</div>
              </div>
            </div>
            {/* decomposition bar */}
            <div className="mt-4">
              <div className="flex h-2 rounded-full overflow-hidden">
                <div style={{ width: `${econ.monthly_cost_in_project / econ.monthly_cost_total * 100}%`, background: 'var(--blue)' }} />
                <div style={{ width: `${econ.monthly_cost_cross_project / econ.monthly_cost_total * 100}%`, background: 'var(--purple)' }} />
                <div style={{ width: `${econ.monthly_cost_ai / econ.monthly_cost_total * 100}%`, background: 'var(--acc)' }} />
              </div>
              <div className="flex gap-4 mt-2 text-[11px] mono" style={{ color: 'var(--ink-dim)' }}>
                <span><span style={{ color: 'var(--blue)' }}>●</span> in-project {unit(econ.cost_per_order_in_project)}</span>
                <span><span style={{ color: 'var(--purple)' }}>●</span> cross-project {unit(econ.cost_per_order_cross_project)}</span>
                <span><span style={{ color: 'var(--acc)' }}>●</span> AI {unit(econ.cost_per_order_ai)}</span>
              </div>
            </div>
          </section>

          {/* ALLOCATION POLICY */}
          <section className="rounded-lg border p-4" style={{ borderColor: '#16794033', background: 'var(--panel)' }}>
            <div className="text-[13px] font-semibold mb-1">Compute allocation policy</div>
            <div className="text-[12px] mb-3" style={{ color: 'var(--ink-dim)' }}>How shared GKE compute is split — the one contested call. Throughput resources (Pub/Sub, Monitoring) split by a fixed signal.</div>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
              {POLICIES.map((p) => {
                const on = policy === p.key
                return <button key={p.key} onClick={() => setPolicy(p.key)}
                  className="text-left rounded-md border px-3 py-2 mono text-[12px] font-semibold"
                  style={{ borderColor: on ? 'var(--acc)' : 'var(--line)', background: on ? '#16794033' : 'transparent', color: on ? 'var(--acc)' : 'var(--ink)' }}>
                  {p.label}
                </button>
              })}
            </div>
            <div className="text-[12px] leading-relaxed" style={{ color: 'var(--ink-dim)' }}>{POLICIES.find((p) => p.key === policy).blurb}</div>
          </section>

          {/* COST BREAKDOWN (in-project) */}
          <BreakdownTable title="Cost breakdown · in-project" subtitle={`compute: ${econ.allocation_policy}`}
            rows={inProj} maxCost={maxCost} subtotal={econ.monthly_cost_in_project} />

          {/* CROSS-PROJECT */}
          <section className="rounded-lg border overflow-hidden" style={{ borderColor: '#2a2140', background: 'var(--panel)' }}>
            <div className="px-4 py-2.5 border-b flex items-center justify-between" style={{ borderColor: 'var(--line)' }}>
              <div>
                <div className="text-[13px] font-semibold flex items-center gap-2">Cross-project flow
                  <span className="text-[10px] mono font-normal px-1.5 py-0.5 rounded" style={{ background: '#2a1a3e', color: 'var(--purple)' }}>shared-platform</span></div>
                <div className="text-[11px]" style={{ color: 'var(--ink-dim)' }}>Global services app1 calls downstream. Labels are common to all callers, so cost is attributed by OTel baggage <span className="mono" style={{ color: 'var(--purple)' }}>product=app1</span>.</div>
              </div>
            </div>
            {cross.map((r) => (
              <ResourceRow key={r.resource_id} r={r} maxCost={maxCost} accent="#a78bfa"
                badge={<span className="text-[10px] mono px-1.5 py-0.5 rounded" style={{ background: '#2a1a3e', color: 'var(--purple)' }}>{r.attributed_by}</span>} />
            ))}
            <SubtotalRow label="Subtotal · cross-project" value={econ.monthly_cost_cross_project} color="var(--purple)" />
          </section>

          {/* AGENTIC WORKFLOW TRACE */}
          {wf && wf.trace_count > 0 && (
            <section className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--line)', background: 'var(--panel)' }}>
              <div className="px-4 py-2.5 border-b flex items-center justify-between" style={{ borderColor: 'var(--line)' }}>
                <div>
                  <div className="text-[13px] font-semibold flex items-center gap-2">Agentic workflow · {wf.workflow_name}
                    <span className="text-[10px] mono font-normal px-1.5 py-0.5 rounded" style={{ background: '#2a1a3e', color: 'var(--purple)' }}>{wf.trace_count} traces</span></div>
                  <div className="text-[11px]" style={{ color: 'var(--ink-dim)' }}>Multi-step agent flow per order. <span style={{ color: 'var(--acc)' }}>{unit(wf.cost_per_successful_trace)}</span> per successful outcome · <span style={{ color: 'var(--red)' }}>{unit(wf.cost_of_failures)}</span> wasted on failed runs.</div>
                </div>
                <div className="text-[11px] mono" style={{ color: 'var(--ink-faint)' }}>{Math.round(wf.success_rate * 100)}% success</div>
              </div>
              {wf.traces.map((tr) => (
                <div key={tr.trace_id} className="px-4 py-2.5 border-b" style={{ borderColor: 'var(--line)' }}>
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: tr.success ? 'var(--acc)' : 'var(--red)' }} />
                    <span className="mono text-[11px]" style={{ color: 'var(--ink-dim)' }}>{tr.transaction_id}</span>
                    {tr.total_retries > 0 && <span className="text-[10px] mono px-1.5 rounded" style={{ background: '#3b2f0e', color: 'var(--amber)' }}>{tr.total_retries} retries</span>}
                    {!tr.success && <span className="text-[10px] mono px-1.5 rounded" style={{ background: '#2e1414', color: 'var(--red)' }}>failed</span>}
                    <span className="mono text-[11px] ml-auto tabnum">{unit(tr.total_cost)}</span>
                  </div>
                  <div className="flex items-center gap-1 flex-wrap pl-3.5">
                    {tr.steps.map((s, i) => (
                      <span key={i} className="flex items-center gap-1">
                        <span className="text-[10px] mono px-1.5 py-0.5 rounded" title={`${s.tokens} tokens · ${s.tool_calls} tool calls · quality ${s.quality}`}
                          style={{ background: s.success ? '#0e2036' : '#2e1414', color: s.success ? 'var(--blue)' : 'var(--red)' }}>
                          {s.agent.replace('-agent', '')} · {unit(s.cost)}
                        </span>
                        {i < tr.steps.length - 1 && <span style={{ color: 'var(--ink-faint)' }}>→</span>}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </section>
          )}

          {/* full total */}
          <div className="rounded-lg border px-4 py-3 flex items-center justify-between" style={{ borderColor: 'var(--line)', background: 'var(--panel-2)' }}>
            <span className="text-[13px] font-semibold">Total attributed to {product}</span>
            <span className="mono tabnum font-semibold text-[16px]" style={{ color: 'var(--acc)' }}>{usd(econ.monthly_cost_total)}<span className="text-[11px]" style={{ color: 'var(--ink-faint)' }}>/mo</span></span>
          </div>
        </main>

        {/* ============ SIDEBAR ============ */}
        <aside className="border-l p-4 space-y-4" style={{ borderColor: 'var(--line)', background: 'var(--panel)' }}>
          {/* AGENT CHAT */}
          <div className="rounded-lg border p-4" style={{ borderColor: '#2a2140', background: 'var(--panel-2)' }}>
            <div className="text-[13px] font-semibold mb-1 flex items-center gap-2">Ask the agent
              <span className="text-[10px] mono font-normal px-1.5 py-0.5 rounded" style={{ background: '#2a1a3e', color: 'var(--purple)' }}>NL → engines</span></div>
            <div className="text-[11px] mb-2" style={{ color: 'var(--ink-faint)' }}>Natural-language questions, answered by calling the real engines. Every answer shows which tools it used.</div>
            <div className="space-y-2 mb-2 overflow-y-auto" style={{ maxHeight: '260px' }}>
              {messages.length === 0 && (
                <div className="space-y-1">
                  {['What does one order cost?', 'How do I get it under 7 cents without hurting AI quality?', 'Show me the agentic workflow trace', 'Why did cost change this month?'].map((s) => (
                    <button key={s} onClick={() => askAgent(s)} className="block w-full text-left text-[11px] mono px-2 py-1.5 rounded border"
                      style={{ borderColor: 'var(--line)', color: 'var(--ink-dim)' }}>{s}</button>
                  ))}
                </div>
              )}
              {messages.map((m, i) => (
                <div key={i} className={m.role === 'user' ? 'text-right' : ''}>
                  <div className="inline-block text-[12px] leading-relaxed px-2.5 py-1.5 rounded-lg text-left"
                    style={{ background: m.role === 'user' ? '#16794033' : 'var(--panel)', color: m.role === 'user' ? 'var(--acc)' : 'var(--ink)', maxWidth: '100%' }}>
                    {m.text}
                    {m.trace && m.trace.length > 0 && <ToolTrace trace={m.trace} mode={m.mode} />}
                  </div>
                </div>
              ))}
              {agentLoading && <div className="text-[11px] mono" style={{ color: 'var(--ink-faint)' }}>calling engines…</div>}
            </div>
            <div className="flex gap-2">
              <input value={question} onChange={(e) => setQuestion(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && askAgent()}
                placeholder="Ask about cost, AI, optimization…" className="flex-1 text-[12px] px-2.5 py-1.5 rounded mono"
                style={{ background: 'var(--panel)', border: '1px solid var(--line)', color: 'var(--ink)', outline: 'none' }} />
              <button onClick={() => askAgent()} className="text-[12px] font-semibold px-3 rounded" style={{ background: 'var(--acc)', color: '#052e16' }}>Ask</button>
            </div>
          </div>

          {/* AI TOKENOMICS */}
          {tok && tok.ai_events_sampled > 0 && (
            <div className="rounded-lg border p-4" style={{ borderColor: '#2a2140', background: 'var(--panel-2)' }}>
              <div className="text-[13px] font-semibold mb-1 flex items-center gap-2">AI tokenomics
                <span className="text-[10px] mono font-normal px-1.5 py-0.5 rounded" style={{ background: '#2a1a3e', color: 'var(--purple)' }}>per outcome</span></div>
              <div className="mono font-semibold tabnum text-[26px] mt-2" style={{ color: 'var(--purple)' }}>{unit(tok.cost_per_successful_outcome)}</div>
              <div className="text-[11px]" style={{ color: 'var(--ink-dim)' }}>cost per <b>successful</b> AI outcome</div>
              <div className="grid grid-cols-2 gap-2 mt-3 text-[11px] mono" style={{ color: 'var(--ink-dim)' }}>
                <Stat label="success rate" val={`${(tok.success_rate * 100).toFixed(0)}%`} warn={tok.success_rate < 0.95} />
                <Stat label="cache hit" val={`${(tok.cache_hit_rate * 100).toFixed(0)}%`} />
                <Stat label="retry rate" val={tok.retry_rate.toFixed(2)} />
                <Stat label="tool calls" val={tok.tool_calls_per_outcome.toFixed(1)} />
              </div>
              <div className="text-[11px] mt-3" style={{ color: 'var(--ink-faint)' }}>model mix</div>
              {Object.entries(tok.model_mix || {}).map(([m, v]) => (
                <div key={m} className="flex justify-between text-[11px] mono" style={{ color: 'var(--ink-dim)' }}>
                  <span>{m}</span><span className="tabnum">{usd(v.cost)} · {v.calls} calls</span>
                </div>
              ))}
            </div>
          )}

          {/* OPTIMIZATION SIMULATOR */}
          <div className="rounded-lg border p-4" style={{ borderColor: 'var(--line)', background: 'var(--panel-2)' }}>
            <div className="text-[13px] font-semibold mb-2">Optimization simulator</div>
            <label className="text-[11px] mono block mb-1" style={{ color: 'var(--ink-dim)' }}>target cost / order: <span style={{ color: 'var(--acc)' }}>{unit(target)}</span></label>
            <input type="range" min="0.04" max="0.09" step="0.001" value={target} onChange={(e) => setTarget(e.target.value)} className="w-full mb-3" />
            <label className="text-[11px] mono block mb-1" style={{ color: 'var(--ink-dim)' }}>min AI success: <span style={{ color: 'var(--acc)' }}>{(minSuccess * 100).toFixed(0)}%</span></label>
            <input type="range" min="0.8" max="1" step="0.01" value={minSuccess} onChange={(e) => setMinSuccess(e.target.value)} className="w-full mb-3" />
            <label className="flex items-center gap-2 text-[12px] mb-3 cursor-pointer" style={{ color: 'var(--ink-dim)' }}>
              <input type="checkbox" checked={protectProd} onChange={(e) => setProtectProd(e.target.checked)} /> protect prod-tagged resources
            </label>
            <button onClick={runOptimize} disabled={optLoading}
              className="w-full text-[12px] font-semibold py-2 rounded" style={{ background: 'var(--acc)', color: '#052e16' }}>
              {optLoading ? 'optimizing…' : 'Run optimization'}
            </button>

            {optResult && (
              <div className="mt-3 space-y-2">
                <div className="text-[12px] mono" style={{ color: optResult.target_met ? 'var(--acc)' : 'var(--amber)' }}>
                  {unit(optResult.current_unit_cost)} → {unit(optResult.projected_unit_cost)} {optResult.target_met ? '✓ target met' : '· target not fully met'}
                </div>
                {optResult.recommended_levers.map((l, i) => (
                  <div key={i} className="rounded-md border p-2 text-[11px]" style={{ borderColor: l.requires_approval ? 'var(--amber)' : 'var(--line)', background: l.requires_approval ? '#241c07' : 'transparent' }}>
                    <div className="font-semibold" style={{ color: l.requires_approval ? 'var(--amber)' : 'var(--ink)' }}>{l.lever}</div>
                    <div className="mono mt-0.5" style={{ color: 'var(--acc)' }}>saves {unit(l.saving_per_order)}/order · {usd(l.annual_saving)}/yr</div>
                    {l.requires_approval && <div className="mono mt-0.5" style={{ color: 'var(--amber)' }}>⊘ needs human approval (prod-tagged)</div>}
                  </div>
                ))}
                {/* blocked levers */}
                {optResult.all_levers.filter((l) => l.constraint_respected === false).map((l, i) => (
                  <div key={`b${i}`} className="rounded-md border p-2 text-[11px]" style={{ borderColor: 'var(--red)', background: '#2e1414' }}>
                    <div className="font-semibold" style={{ color: 'var(--red)' }}>{l.lever}</div>
                    <div className="mono mt-0.5" style={{ color: 'var(--red)' }}>blocked — {l.risk_to_success}</div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* RCA */}
          {comp && (
            <div className="rounded-lg border p-4" style={{ borderColor: 'var(--line)', background: 'var(--panel-2)' }}>
              <div className="text-[13px] font-semibold mb-1">Why it changed</div>
              <div className="text-[12px] mono mb-1" style={{ color: deltaUp ? 'var(--red)' : 'var(--acc)' }}>
                {unit(comp.previous_cost_per_order)} → {unit(comp.current_cost_per_order)} ({comp.change_pct > 0 ? '+' : ''}{comp.change_pct}%)
              </div>
              <div className="text-[12px] leading-relaxed" style={{ color: 'var(--ink-dim)' }}>{comp.primary_driver}</div>
            </div>
          )}
        </aside>
      </div>
      )}
    </Shell>
  )
}

/* ---------- sub-components ---------- */
function Shell({ children, health, view, setView }) {
  return <div className="min-h-screen">
    <header className="border-b px-5 py-3 flex items-center justify-between" style={{ borderColor: 'var(--line)', background: 'var(--panel)' }}>
      <div className="flex items-baseline gap-3">
        <span className="mono font-semibold text-[15px] tracking-tight">CostGraph<span style={{ color: 'var(--acc)' }}>AI</span></span>
        <span className="text-[12px]" style={{ color: 'var(--ink-faint)' }}>app1 · Order Processing · cloud + AI unit economics</span>
      </div>
      <div className="flex items-center gap-4">
        {setView && (
          <div className="flex rounded-md border overflow-hidden" style={{ borderColor: 'var(--line)' }}>
            {['dashboard', 'flow'].map((v) => (
              <button key={v} onClick={() => setView(v)}
                className="text-[12px] mono px-3 py-1"
                style={{ background: view === v ? 'var(--acc)' : 'transparent', color: view === v ? '#052e16' : 'var(--ink-dim)', fontWeight: view === v ? 600 : 400 }}>
                {v === 'flow' ? 'Cost Flow' : 'Dashboard'}
              </button>
            ))}
          </div>
        )}
        {health && <div className="flex items-center gap-2 text-[11px] mono" style={{ color: 'var(--ink-dim)' }}>
          <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--acc)' }} />
          {health.planes.cost + health.planes.telemetry + health.planes.business + health.planes.ai_usage} records · 4 planes live
        </div>}
      </div>
    </header>
    {children}
  </div>
}

function BreakdownTable({ title, subtitle, rows, maxCost, subtotal }) {
  return <section className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--line)', background: 'var(--panel)' }}>
    <div className="px-4 py-2.5 border-b flex items-center justify-between" style={{ borderColor: 'var(--line)' }}>
      <div className="text-[13px] font-semibold">{title}</div>
      <div className="text-[11px] mono" style={{ color: 'var(--ink-faint)' }}>{subtitle}</div>
    </div>
    {rows.map((r) => <ResourceRow key={r.resource_id} r={r} maxCost={maxCost}
      badge={<span className="text-[10px] mono px-1.5 py-0.5 rounded" style={{ background: r.method === 'dedicated' ? '#0e2a1a' : '#1a2230', color: r.method === 'dedicated' ? 'var(--acc)' : 'var(--ink-faint)' }}>{r.attributed_by}</span>} />)}
    <SubtotalRow label="Subtotal · in-project" value={subtotal} />
  </section>
}

function ResourceRow({ r, maxCost, badge, accent }) {
  const [open, setOpen] = useState(false)
  return <div className="border-b" style={{ borderColor: 'var(--line)' }}>
    <div className="px-4 py-2.5 flex items-center gap-3 cursor-pointer" onClick={() => setOpen(!open)}>
      <span className="w-1.5 h-6 rounded-sm shrink-0" style={{ background: accent || svcColor(r.service) }} />
      <div className="w-[150px] shrink-0">
        <div className="text-[13px] font-medium">{r.service}</div>
        <div className="text-[11px] mono truncate" style={{ color: 'var(--ink-faint)' }}>{r.name}</div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {r.scope !== 'ai' && <span className="text-[10px] mono px-1.5 py-0.5 rounded" style={{ background: '#3b2f0e', color: 'var(--amber)' }}>{Math.round(r.share * 100)}%</span>}
        {badge}
        {r.prod_tagged && <span className="text-[10px] mono px-1.5 py-0.5 rounded" style={{ background: '#2e1414', color: 'var(--red)' }}>prod</span>}
      </div>
      <div className="flex-1 bar-track h-2 min-w-[40px]"><div className="bar-fill" style={{ width: `${r.attributed_cost / maxCost * 100}%`, background: accent || svcColor(r.service) }} /></div>
      <div className="mono tabnum text-[13px] w-[70px] text-right">{usd(r.attributed_cost)}</div>
    </div>
    {open && <div className="px-4 pb-2.5 pl-[42px] text-[11px] leading-relaxed" style={{ color: 'var(--ink-faint)' }}>{r.evidence}</div>}
  </div>
}

function SubtotalRow({ label, value, color }) {
  return <div className="px-4 py-2.5 flex items-center justify-between" style={{ background: 'var(--panel-2)' }}>
    <span className="text-[12px]" style={{ color: 'var(--ink-dim)' }}>{label}</span>
    <span className="mono tabnum font-semibold text-[15px]" style={{ color: color || 'var(--ink)' }}>{usd(value)}<span className="text-[11px]" style={{ color: 'var(--ink-faint)' }}>/mo</span></span>
  </div>
}

function Stat({ label, val, warn }) {
  return <div><div style={{ color: 'var(--ink-faint)' }}>{label}</div><div className="tabnum" style={{ color: warn ? 'var(--red)' : 'var(--ink)' }}>{val}</div></div>
}

function ToolTrace({ trace, mode }) {
  const [open, setOpen] = useState(false)
  return <div className="mt-1.5 pt-1.5" style={{ borderTop: '1px solid var(--line)' }}>
    <button onClick={() => setOpen(!open)} className="text-[10px] mono" style={{ color: 'var(--purple)' }}>
      {open ? '▾' : '▸'} how I got this · {trace.length} engine{trace.length > 1 ? 's' : ''} called · {mode}
    </button>
    {open && <div className="mt-1 space-y-1">
      {trace.map((t, i) => (
        <div key={i} className="text-[10px] mono" style={{ color: 'var(--ink-faint)' }}>
          <span style={{ color: 'var(--blue)' }}>{t.tool}</span> → {JSON.stringify(t.returned)}
        </div>
      ))}
    </div>}
  </div>
}
