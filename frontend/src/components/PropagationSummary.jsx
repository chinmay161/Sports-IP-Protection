// src/components/PropagationSummary.jsx
// Six stat tiles across the top of the propagation page.

function formatNumber(n) {
  if (n == null) return "—"
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}

function formatDuration(ms) {
  if (ms == null) return "—"
  const sec = ms / 1000
  if (sec < 60) return `${sec.toFixed(0)}s`
  const min = sec / 60
  if (min < 60) return `${min.toFixed(0)}m`
  const hr = min / 60
  if (hr < 24) return `${hr.toFixed(1)}h`
  return `${(hr / 24).toFixed(1)}d`
}

function Tile({ label, value, hint, accent = "slate" }) {
  const accents = {
    slate: "text-slate-100",
    red: "text-red-300",
    orange: "text-orange-300",
    cyan: "text-cyan-300",
    emerald: "text-emerald-300",
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

export default function PropagationSummary({ summary }) {
  if (!summary) return null

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
      <Tile
        label="Infringing copies"
        value={formatNumber(summary.total_infringing_copies)}
        accent="red"
      />
      <Tile
        label="Estimated views"
        value={formatNumber(summary.total_estimated_views)}
        accent="orange"
      />
      <Tile
        label="Platforms"
        value={summary.platforms_reached?.length ?? 0}
        hint={summary.platforms_reached?.join(" · ")}
      />
      <Tile
        label="Countries"
        value={summary.countries_reached ?? 0}
      />
      <Tile
        label="Fastest repost"
        value={formatDuration(summary.fastest_repost_ms)}
        hint={`Origin: ${summary.origin_platform ?? "unknown"}`}
        accent="cyan"
      />
      <Tile
        label="Peak velocity"
        value={`${summary.peak_velocity_index?.toFixed(1) ?? 0}/hr`}
        hint="New copies per hour at peak"
        accent="emerald"
      />
    </div>
  )
}