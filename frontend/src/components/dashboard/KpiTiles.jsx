// src/components/dashboard/KpiTiles.jsx
function formatNumber(n) {
  if (n == null) return "—"
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}

function formatDuration(seconds) {
  if (seconds == null) return "—"
  if (seconds < 60) return `${seconds.toFixed(0)}s`
  const m = seconds / 60
  if (m < 60) return `${m.toFixed(0)}m`
  const h = m / 60
  if (h < 24) return `${h.toFixed(1)}h`
  return `${(h / 24).toFixed(1)}d`
}

function Tile({ label, value, hint, accent = "slate" }) {
  const accents = {
    slate:   "text-slate-100",
    red:     "text-red-300",
    orange:  "text-orange-300",
    cyan:    "text-cyan-300",
    emerald: "text-emerald-300",
    amber:   "text-amber-300",
  }
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </div>
      <div className={`mt-1 text-2xl font-bold ${accents[accent] ?? accents.slate}`}>
        {value}
      </div>
      {hint && <div className="mt-1 text-[11px] text-slate-500">{hint}</div>}
    </div>
  )
}

export default function KpiTiles({ kpis }) {
  if (!kpis) return null
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <Tile
        label="Active alerts"
        value={formatNumber(kpis.active_alerts)}
        hint={`of ${formatNumber(kpis.total_alerts)} total`}
        accent="cyan"
      />
      <Tile
        label="Critical open"
        value={formatNumber(kpis.critical_open)}
        hint="Needs attention"
        accent="red"
      />
      <Tile
        label="Takedown rate"
        value={`${(kpis.takedown_rate * 100).toFixed(0)}%`}
        hint="DMCA sent or resolved"
        accent="emerald"
      />
      <Tile
        label="Mean time to resolve"
        value={formatDuration(kpis.mean_time_to_resolution_s)}
        hint="Avg of resolved alerts"
        accent="amber"
      />
      <Tile
        label="Assets protected"
        value={formatNumber(kpis.assets_protected)}
        accent="slate"
      />
      <Tile
        label="Total alerts"
        value={formatNumber(kpis.total_alerts)}
        hint="All time"
        accent="orange"
      />
    </div>
  )
}