import { useState, useEffect, useRef, useCallback } from 'react'
import { api } from './api'

const usd = (n) => '$' + (n ?? 0).toLocaleString('en-US', { maximumFractionDigits: 0 })
const scopeColor = { PRODUCT: '#4ade80', RESOURCE: '#60a5fa', SHARED_PLATFORM: '#c4a5ff', AI_AGENT: '#4ade80' }
const methodLabel = {
  dedicated: 'dedicated', consumption: 'by policy', message_attribute: 'by messages',
  label: 'by label', otel_baggage: 'OTel baggage', call_share: 'call share',
}

/**
 * CostFlowGraph — a live, force-directed graph of how one product's cost flows
 * through every resource it touches. Product node in the center; resource nodes
 * around it; edges carry the attributed dollar amount and attribution method.
 * Self-contained (no graph library): a tiny spring simulation + SVG + drag.
 */
export default function CostFlowGraph({ product = 'app1', policy = 'cpu_request' }) {
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const [nodes, setNodes] = useState([])
  const [hover, setHover] = useState(null)
  const dragRef = useRef(null)
  const rafRef = useRef(null)
  const W = 900, H = 560, CX = W / 2, CY = H / 2

  useEffect(() => {
    api.graph(product, policy).then(setData).catch((e) => setErr(e.message))
  }, [product, policy])

  // initialize node positions once data arrives
  useEffect(() => {
    if (!data) return
    const rs = data.nodes.filter((n) => n.type !== 'PRODUCT')
    const prod = data.nodes.find((n) => n.type === 'PRODUCT')
    // attributed cost per edge for sizing
    const edgeByTarget = Object.fromEntries(data.edges.map((e) => [e.target, e]))
    const init = []
    if (prod) init.push({ ...prod, x: CX, y: CY, fx: CX, fy: CY, r: 46, attributed: 0 })
    const n = rs.length
    rs.forEach((node, i) => {
      const ang = (i / n) * Math.PI * 2 - Math.PI / 2
      const e = edgeByTarget[node.id]
      const attributed = e ? node.monthly_cost * e.attribution_share : node.monthly_cost
      init.push({
        ...node, x: CX + Math.cos(ang) * 230, y: CY + Math.sin(ang) * 190,
        r: Math.max(20, Math.min(46, 16 + Math.sqrt(attributed) * 0.55)),
        attributed, method: e?.method, share: e?.attribution_share, scope: node.type,
      })
    })
    setNodes(init)
  }, [data])

  // spring simulation: repulsion between nodes + attraction of each to the product center ring
  const tick = useCallback(() => {
    setNodes((prev) => {
      if (prev.length === 0) return prev
      const next = prev.map((n) => ({ ...n }))
      for (let i = 0; i < next.length; i++) {
        const a = next[i]
        if (a.fx != null) { a.x = a.fx; a.y = a.fy; continue }
        let vx = 0, vy = 0
        for (let j = 0; j < next.length; j++) {
          if (i === j) continue
          const b = next[j]
          let dx = a.x - b.x, dy = a.y - b.y
          let d2 = dx * dx + dy * dy || 1
          const rep = 9000 / d2
          vx += (dx / Math.sqrt(d2)) * rep
          vy += (dy / Math.sqrt(d2)) * rep
        }
        // gentle pull toward a ring around center
        const dcx = a.x - CX, dcy = a.y - CY
        const dist = Math.sqrt(dcx * dcx + dcy * dcy) || 1
        const target = 210
        const pull = (dist - target) * 0.02
        vx -= (dcx / dist) * pull * 8
        vy -= (dcy / dist) * pull * 8
        a.x += Math.max(-6, Math.min(6, vx))
        a.y += Math.max(-6, Math.min(6, vy))
        a.x = Math.max(a.r, Math.min(W - a.r, a.x))
        a.y = Math.max(a.r, Math.min(H - a.r, a.y))
      }
      return next
    })
    rafRef.current = requestAnimationFrame(tick)
  }, [])

  useEffect(() => {
    if (nodes.length === 0) return
    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [nodes.length, tick])

  // drag handlers
  const onDown = (id) => (e) => { dragRef.current = id; e.preventDefault() }
  const onMove = (e) => {
    if (!dragRef.current) return
    const svg = e.currentTarget.getBoundingClientRect()
    const x = ((e.clientX - svg.left) / svg.width) * W
    const y = ((e.clientY - svg.top) / svg.height) * H
    setNodes((prev) => prev.map((n) => n.id === dragRef.current ? { ...n, x, y, fx: x, fy: y } : n))
  }
  const onUp = () => {
    const id = dragRef.current; dragRef.current = null
    // release fixed unless it's the product node
    setNodes((prev) => prev.map((n) => (n.id === id && n.type !== 'PRODUCT') ? { ...n, fx: null, fy: null } : n))
  }

  if (err) return <div className="p-6 mono text-[13px]" style={{ color: 'var(--red)' }}>Graph error: {err}</div>
  if (!data) return <div className="p-6 mono text-[13px]" style={{ color: 'var(--ink-dim)' }}>Loading cost graph…</div>

  const prod = nodes.find((n) => n.type === 'PRODUCT')
  const total = data.nodes.filter(n=>n.type!=='PRODUCT').reduce((s, n) => {
    const e = data.edges.find((x) => x.target === n.id); return s + (e ? n.monthly_cost * e.attribution_share : 0)
  }, 0)

  return (
    <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--line)', background: 'var(--panel)' }}>
      <div className="px-4 py-2.5 border-b flex items-center justify-between" style={{ borderColor: 'var(--line)' }}>
        <div>
          <div className="text-[13px] font-semibold">Cost flow graph · {product}</div>
          <div className="text-[11px]" style={{ color: 'var(--ink-dim)' }}>How cost flows from the product to every resource it touches. Node size = attributed cost · drag to explore · hover for detail.</div>
        </div>
        <div className="flex gap-3 text-[10px] mono" style={{ color: 'var(--ink-dim)' }}>
          <span><span style={{ color: '#60a5fa' }}>●</span> in-project</span>
          <span><span style={{ color: '#c4a5ff' }}>●</span> cross-project</span>
          <span><span style={{ color: '#4ade80' }}>●</span> AI / product</span>
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', display: 'block', cursor: dragRef.current ? 'grabbing' : 'default' }}
        onMouseMove={onMove} onMouseUp={onUp} onMouseLeave={onUp}>
        {/* edges */}
        {prod && nodes.filter((n) => n.type !== 'PRODUCT').map((n) => {
          const mid = { x: (prod.x + n.x) / 2, y: (prod.y + n.y) / 2 }
          const strong = hover === n.id
          return (
            <g key={'e' + n.id}>
              <line x1={prod.x} y1={prod.y} x2={n.x} y2={n.y}
                stroke={strong ? scopeColor[n.scope] || '#60a5fa' : '#2a3444'}
                strokeWidth={strong ? 2.5 : Math.max(1, Math.min(5, n.attributed / 1200))} />
              {strong && (
                <g>
                  <rect x={mid.x - 46} y={mid.y - 11} width="92" height="22" rx="4" fill="#0a0e14" stroke="var(--line)" />
                  <text x={mid.x} y={mid.y + 4} textAnchor="middle" fontSize="10" className="mono" fill={scopeColor[n.scope]}>
                    {usd(n.attributed)} · {methodLabel[n.method] || ''}
                  </text>
                </g>
              )}
            </g>
          )
        })}
        {/* nodes */}
        {nodes.map((n) => {
          const isProd = n.type === 'PRODUCT'
          const col = scopeColor[n.scope || n.type] || '#60a5fa'
          return (
            <g key={n.id} transform={`translate(${n.x},${n.y})`}
              onMouseEnter={() => setHover(n.id)} onMouseLeave={() => setHover(null)}
              onMouseDown={onDown(n.id)} style={{ cursor: 'grab' }}>
              <circle r={n.r} fill={isProd ? '#0e2a1a' : '#111721'} stroke={col} strokeWidth={isProd ? 2.5 : 1.5} />
              {n.prod_tagged && <circle r={n.r} fill="none" stroke="#f87171" strokeWidth="1" strokeDasharray="3 3" />}
              <text textAnchor="middle" y={isProd ? -2 : ((n.scope === 'SHARED_PLATFORM' || n.scope === 'AI_AGENT') ? -1 : 4)} fontSize={isProd ? 13 : 11} fontWeight="600" fill="var(--ink)"
                style={{ pointerEvents: 'none' }}>
                {(() => {
                  // Cross-project: show the SERVICE NAME (fraud-check), not the platform (GKE).
                  // AI: show the AGENT NAME (fraud agent), not the provider (OpenAI).
                  // In-project: show the GCP service (GKE, Pub/Sub, ...).
                  const label = (n.scope === 'SHARED_PLATFORM' || n.scope === 'AI_AGENT')
                    ? (n.name || n.id)
                    : (n.attributes?.service || n.name || n.id)
                  return label.replace(/-agent$/, '').replace(/-/g, ' ').replace(/ \(.*\)/, '').slice(0, 14)
                })()}
              </text>
              {/* platform/provider sublabel so the node's substrate is clear */}
              {n.scope === 'SHARED_PLATFORM' && (
                <text textAnchor="middle" y={11} fontSize="8.5" className="mono" fill="var(--ink-faint)" style={{ pointerEvents: 'none' }}>
                  on {n.attributes?.service || 'GKE'}
                </text>
              )}
              {n.scope === 'AI_AGENT' && (
                <text textAnchor="middle" y={11} fontSize="8.5" className="mono" fill="var(--ink-faint)" style={{ pointerEvents: 'none' }}>
                  on {n.attributes?.service || 'OpenAI'}
                </text>
              )}
              {isProd
                ? <text textAnchor="middle" y={14} fontSize="11" className="mono" fill="#4ade80" style={{ pointerEvents: 'none' }}>{usd(total)}/mo</text>
                : <text textAnchor="middle" y={n.r + 13} fontSize="10" className="mono" fill="var(--ink-dim)" style={{ pointerEvents: 'none' }}>{usd(n.attributed)}</text>}
            </g>
          )
        })}
      </svg>
    </div>
  )
}
