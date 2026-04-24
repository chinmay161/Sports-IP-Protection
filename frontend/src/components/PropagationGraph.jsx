// src/components/PropagationGraph.jsx
// d3-force computes node positions; React owns DOM and drag entirely.
import { useEffect, useMemo, useRef, useState } from "react"
import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
} from "d3-force"

const WIDTH = 800
const HEIGHT = 500

const SEVERITY_FILL = {
  critical: "#ef4444",
  high:     "#f97316",
  medium:   "#eab308",
  low:      "#64748b",
}

const STATUS_STROKE = {
  new:        "#ef4444",
  dmca_sent:  "#f97316",
  resolved:   "#64748b",
}

const RELATION_STROKE = {
  repost:  "#475569",
  mirror:  "#0ea5e9",
  embed:   "#a855f7",
  unknown: "#334155",
}

function nodeRadius(viewCount) {
  if (viewCount == null || viewCount <= 0) return 6
  const r = Math.sqrt(viewCount) / 50
  return Math.max(6, Math.min(32, r))
}

function nodeOpacity(confidence) {
  if (confidence == null) return 0.7
  return 0.55 + Math.min(1, confidence) * 0.45
}

function edgeWidth(deltaMs, maxDelta) {
  if (!deltaMs || !maxDelta) return 1
  const norm = Math.min(1, deltaMs / maxDelta)
  return 0.5 + 3 * (1 - norm)
}

function NodeShape({ node, r, onMouseDown, onMouseEnter, onMouseLeave }) {
  const fill = SEVERITY_FILL[node.severity] ?? SEVERITY_FILL.low
  const stroke = STATUS_STROKE[node.status] ?? STATUS_STROKE.new
  const opacity = nodeOpacity(node.confidence)
  const common = {
    fill,
    stroke,
    strokeWidth: 2,
    opacity,
    style: { cursor: "grab" },
    onMouseDown,
    onMouseEnter,
    onMouseLeave,
  }

  if (node.type === "origin") {
    const points = []
    for (let i = 0; i < 10; i++) {
      const angle = (Math.PI / 5) * i - Math.PI / 2
      const radius = i % 2 === 0 ? r * 1.3 : r * 0.55
      points.push(`${Math.cos(angle) * radius},${Math.sin(angle) * radius}`)
    }
    return <polygon points={points.join(" ")} {...common} />
  }
  if (node.type === "mirror") {
    return <rect x={-r} y={-r} width={r * 2} height={r * 2} {...common} />
  }
  return <circle r={r} {...common} />
}

export default function PropagationGraph({ graph }) {
  const svgRef = useRef(null)
  const simRef = useRef(null)
  const draggingRef = useRef(null) // { node, pointerId } | null
  const [hover, setHover] = useState(null)
  const [, setTick] = useState(0)

  const { nodes, links, maxDelta } = useMemo(() => {
    if (!graph) return { nodes: [], links: [], maxDelta: 0 }
    const ns = graph.nodes.map((n) => ({ ...n }))
    const ls = graph.edges.map((e) => ({ ...e }))
    const md = graph.edges.reduce((m, e) => Math.max(m, e.delta_ms ?? 0), 0)
    return { nodes: ns, links: ls, maxDelta: md }
  }, [graph])

  useEffect(() => {
    if (!nodes.length) return

    const sim = forceSimulation(nodes)
      .force("link", forceLink(links).id((d) => d.id).distance(80).strength(0.6))
      .force("charge", forceManyBody().strength(-220))
      .force("center", forceCenter(WIDTH / 2, HEIGHT / 2))
      .force("collide", forceCollide().radius((d) => nodeRadius(d.view_count) + 4))
      .alpha(1)
      .alphaDecay(0.04)

    sim.on("tick", () => setTick((t) => t + 1))
    simRef.current = sim

    return () => {
      sim.stop()
      simRef.current = null
    }
  }, [nodes, links])

  /** Convert client (mouse) coords to SVG viewBox coords. */
  const toSvgCoords = (clientX, clientY) => {
    const svg = svgRef.current
    if (!svg) return { x: 0, y: 0 }
    const pt = svg.createSVGPoint()
    pt.x = clientX
    pt.y = clientY
    const ctm = svg.getScreenCTM()
    if (!ctm) return { x: 0, y: 0 }
    const { x, y } = pt.matrixTransform(ctm.inverse())
    return { x, y }
  }

  const handleNodeMouseDown = (e, node) => {
    e.preventDefault()
    e.stopPropagation()
    const { x, y } = toSvgCoords(e.clientX, e.clientY)
    draggingRef.current = { node, offsetX: node.x - x, offsetY: node.y - y }
    node.fx = node.x
    node.fy = node.y
    if (simRef.current) simRef.current.alphaTarget(0.3).restart()
  }

  const handleSvgMouseMove = (e) => {
    if (!draggingRef.current) return
    const { node, offsetX, offsetY } = draggingRef.current
    const { x, y } = toSvgCoords(e.clientX, e.clientY)
    node.fx = x + offsetX
    node.fy = y + offsetY
  }

  const handleSvgMouseUp = () => {
    if (!draggingRef.current) return
    if (simRef.current) simRef.current.alphaTarget(0)
    draggingRef.current = null
  }

  if (!graph?.nodes?.length) {
    return (
      <div className="rounded-xl border border-dashed border-slate-800 p-10 text-center text-sm text-slate-500">
        No propagation graph data.
      </div>
    )
  }

  return (
    <div className="relative rounded-xl border border-slate-800 bg-slate-900/60 p-2">
      <div className="px-2 pb-2 pt-1 text-sm font-semibold text-slate-100">
        Propagation graph
        <span className="ml-2 text-[11px] font-normal text-slate-500">
          {nodes.length} nodes · {links.length} edges · drag to reposition
        </span>
      </div>

      <svg
        ref={svgRef}
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="xMidYMid meet"
        className="h-[500px] w-full select-none"
        onMouseMove={handleSvgMouseMove}
        onMouseUp={handleSvgMouseUp}
        onMouseLeave={() => {
          handleSvgMouseUp()
          setHover(null)
        }}
      >
        {/* Edges first so nodes render on top */}
        <g>
          {links.map((l) => {
            const sx = typeof l.source === "object" ? l.source.x : 0
            const sy = typeof l.source === "object" ? l.source.y : 0
            const tx = typeof l.target === "object" ? l.target.x : 0
            const ty = typeof l.target === "object" ? l.target.y : 0
            return (
              <line
                key={l.id}
                x1={sx ?? 0}
                y1={sy ?? 0}
                x2={tx ?? 0}
                y2={ty ?? 0}
                stroke={RELATION_STROKE[l.relation] ?? RELATION_STROKE.unknown}
                strokeWidth={edgeWidth(l.delta_ms, maxDelta)}
                strokeOpacity={0.5}
              />
            )
          })}
        </g>

        {/* Nodes */}
        <g>
          {nodes.map((n) => {
            const r = nodeRadius(n.view_count)
            return (
              <g key={n.id} transform={`translate(${n.x ?? 0}, ${n.y ?? 0})`}>
                <NodeShape
                  node={n}
                  r={r}
                  onMouseDown={(e) => handleNodeMouseDown(e, n)}
                  onMouseEnter={() => setHover({ node: n, x: n.x, y: n.y })}
                  onMouseLeave={() => setHover(null)}
                />
                <text
                  y={r + 12}
                  textAnchor="middle"
                  fontSize="9"
                  fill="#94a3b8"
                  pointerEvents="none"
                >
                  {n.platform}
                </text>
              </g>
            )
          })}
        </g>
      </svg>

      {hover && (
        <div
          className="pointer-events-none absolute z-10 rounded-lg border border-slate-700 bg-slate-900/95 px-3 py-2 text-xs shadow-lg"
          style={{
            left: `calc(${(hover.x / WIDTH) * 100}% + 12px)`,
            top: `calc(${(hover.y / HEIGHT) * 100}% + 40px)`,
            maxWidth: 260,
          }}
        >
          <div className="font-semibold text-slate-100">
            {hover.node.channel ?? "(unknown channel)"}
          </div>
          <div className="text-[11px] text-slate-400">
            {hover.node.platform} · {hover.node.geo_country ?? "??"}
          </div>
          <div className="mt-1 flex items-center gap-2 text-[11px]">
            <span className="rounded bg-slate-800 px-1.5 py-0.5 uppercase">
              {hover.node.severity}
            </span>
            <span className="text-slate-400">
              {(hover.node.confidence * 100).toFixed(0)}% conf
            </span>
          </div>
          <div className="mt-1 text-[11px] text-slate-300">
            {hover.node.view_count != null
              ? `${hover.node.view_count.toLocaleString()} views`
              : "views unknown"}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-2 pt-2 text-[10px] text-slate-500">
        <span>Severity:</span>
        {Object.entries(SEVERITY_FILL).map(([k, v]) => (
          <span key={k} className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full" style={{ backgroundColor: v }} />
            {k}
          </span>
        ))}
        <span className="ml-3">Shape:</span>
        <span>★ origin</span>
        <span>● repost</span>
        <span>■ mirror</span>
        <span className="ml-3">Edge:</span>
        <span>thicker = faster repost</span>
      </div>
    </div>
  )
}