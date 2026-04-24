// src/components/dashboard/PlatformBreakdown.jsx

const PLATFORM_COLORS = {
  youtube:   "#ef4444",
  tiktok:    "#22d3ee",
  telegram:  "#60a5fa",
  instagram: "#ec4899",
  twitter:   "#0ea5e9",
  web:       "#a78bfa",
  unknown:   "#64748b",
}

export default function PlatformBreakdown({ platforms = [] }) {
  if (!platforms.length) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="text-sm font-semibold text-slate-100">Top platforms</div>
        <div className="mt-4 text-xs text-slate-500">No platform data yet.</div>
      </div>
    )
  }

  const max = Math.max(...platforms.map((p) => p.count))

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-3">
        <div className="text-sm font-semibold text-slate-100">Top platforms</div>
        <div className="text-[11px] text-slate-500">Infringements by host platform</div>
      </div>

      <ul className="space-y-2">
        {platforms.map((p) => {
          const width = max > 0 ? (p.count / max) * 100 : 0
          const color = PLATFORM_COLORS[p.platform] ?? PLATFORM_COLORS.unknown
          return (
            <li key={p.platform} className="flex items-center gap-3">
              <span className="w-20 shrink-0 truncate text-xs text-slate-300" title={p.platform}>
                {p.platform}
              </span>
              <div className="relative flex-1 h-2 rounded-full bg-slate-800">
                <div
                  className="absolute left-0 top-0 h-full rounded-full transition-all"
                  style={{ width: `${width}%`, backgroundColor: color, opacity: 0.8 }}
                />
              </div>
              <span className="w-8 shrink-0 text-right text-xs font-semibold text-slate-200">
                {p.count}
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}