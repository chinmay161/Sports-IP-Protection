// src/components/dashboard/AlertsOverTime.jsx
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

function formatDay(iso) {
  if (!iso) return ""
  const d = new Date(iso + "T00:00:00")
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  const row = payload[0].payload
  const total = row.total || 0
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/95 px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 font-semibold text-slate-100">{formatDay(label)}</div>
      <div className="text-slate-300">{total} total</div>
      {row.critical > 0 && <div className="text-red-300">{row.critical} critical</div>}
      {row.high > 0 && <div className="text-orange-300">{row.high} high</div>}
      {row.medium > 0 && <div className="text-yellow-300">{row.medium} medium</div>}
      {row.low > 0 && <div className="text-slate-300">{row.low} low</div>}
    </div>
  )
}

export default function AlertsOverTime({ data, windowDays }) {
  if (!data?.length) return null

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-100">Alerts over time</div>
          <div className="text-[11px] text-slate-500">Last {windowDays} days · stacked by severity</div>
        </div>
      </div>

      <div style={{ width: "100%", height: 240 }}>
        <ResponsiveContainer>
          <AreaChart data={data} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
            <defs>
              <linearGradient id="grad-critical" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#ef4444" stopOpacity={0.55} />
                <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="grad-high" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#f97316" stopOpacity={0.55} />
                <stop offset="95%" stopColor="#f97316" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="grad-medium" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#eab308" stopOpacity={0.5} />
                <stop offset="95%" stopColor="#eab308" stopOpacity={0} />
              </linearGradient>
              <linearGradient id="grad-low" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="#64748b" stopOpacity={0.45} />
                <stop offset="95%" stopColor="#64748b" stopOpacity={0} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tickFormatter={formatDay}
              stroke="#64748b"
              fontSize={11}
              tickLine={false}
              axisLine={false}
            />
            <YAxis stroke="#64748b" fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} />
            <Tooltip content={<CustomTooltip />} cursor={{ stroke: "#475569", strokeDasharray: "3 3" }} />
            <Legend
              wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
              iconType="circle"
            />
            <Area stackId="1" type="monotone" dataKey="critical" name="Critical" stroke="#ef4444" fill="url(#grad-critical)" strokeWidth={1.5} />
            <Area stackId="1" type="monotone" dataKey="high"     name="High"     stroke="#f97316" fill="url(#grad-high)"     strokeWidth={1.5} />
            <Area stackId="1" type="monotone" dataKey="medium"   name="Medium"   stroke="#eab308" fill="url(#grad-medium)"   strokeWidth={1.5} />
            <Area stackId="1" type="monotone" dataKey="low"      name="Low"      stroke="#64748b" fill="url(#grad-low)"      strokeWidth={1.5} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}