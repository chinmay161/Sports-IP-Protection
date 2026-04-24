// src/components/PropagationTimeline.jsx
// Recharts area chart of new_nodes per hour bucket, with peak bucket highlighted.
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

function formatTime(iso) {
  if (!iso) return ""
  const d = new Date(iso)
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
}

function CustomTooltip({ active, payload }) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/95 px-3 py-2 text-xs shadow-lg">
      <div className="font-semibold text-slate-100">{formatTime(row.bucket_start)}</div>
      <div className="mt-1 text-amber-300">+{row.new_nodes} new copies</div>
      <div className="text-slate-300">{row.cumulative_nodes} total · {row.cumulative_views.toLocaleString()} views</div>
    </div>
  )
}

export default function PropagationTimeline({ timeline }) {
  if (!timeline?.buckets?.length) return null

  // Recharts plays nicest with already-formatted x-axis labels.
  const data = timeline.buckets.map((b) => ({
    ...b,
    label: formatTime(b.bucket_start),
  }))
  const peakLabel = formatTime(timeline.peak_bucket)

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-100">Spread velocity</div>
          <div className="text-[11px] text-slate-500">
            Peak velocity {timeline.velocity_index.toFixed(1)} new copies/hr at {peakLabel}
          </div>
        </div>
        <div className="text-[10px] uppercase tracking-wider text-slate-500">
          {timeline.bucket_size_ms / 60000} min buckets
        </div>
      </div>

      <div style={{ width: "100%", height: 224 }}>
        <ResponsiveContainer>
          <AreaChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
            <defs>
              <linearGradient id="newGradient" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#fbbf24" stopOpacity={0.5} />
                <stop offset="95%" stopColor="#fbbf24" stopOpacity={0}   />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
            <XAxis dataKey="label" stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} />
            <YAxis stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} />
            <Tooltip content={<CustomTooltip />} cursor={{ stroke: "#475569", strokeDasharray: "3 3" }} />
            <ReferenceLine
              x={peakLabel}
              stroke="#f97316"
              strokeDasharray="4 2"
              label={{ value: "peak", position: "top", fill: "#f97316", fontSize: 10 }}
            />
            <Area
              type="monotone"
              dataKey="new_nodes"
              stroke="#fbbf24"
              strokeWidth={2}
              fill="url(#newGradient)"
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}