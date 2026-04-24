// src/components/dashboard/PriorityQueue.jsx
import StatusBadge from "../StatusBadge.jsx"

function formatWhen(iso) {
  if (!iso) return ""
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  })
}

export default function PriorityQueue({ items = [], onGoToAlerts }) {
  if (!items.length) {
    return (
      <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="text-sm font-semibold text-slate-100">Priority queue</div>
        <div className="mt-4 text-xs text-slate-500">Nothing urgent. Nice.</div>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-100">Priority queue</div>
          <div className="text-[11px] text-slate-500">{items.length} items needing attention</div>
        </div>
        {onGoToAlerts && (
          <button
            onClick={onGoToAlerts}
            className="text-[11px] text-cyan-300 hover:text-cyan-200"
          >
            View all alerts →
          </button>
        )}
      </div>

      <ul className="space-y-2">
        {items.map((a) => (
          <li
            key={a.id}
            className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2"
          >
            <StatusBadge kind="severity" value={a.severity_label} />
            <div className="min-w-0 flex-1">
              <div className="truncate text-xs font-medium text-slate-200" title={a.infringing_url}>
                {a.infringing_url}
              </div>
              <div className="text-[11px] text-slate-500">
                {a.platform ?? "unknown"} ·{" "}
                {a.assigned_to ? a.assigned_to.split("@")[0] : "unassigned"} · {formatWhen(a.created_at)}
              </div>
            </div>
            <StatusBadge kind="status" value={a.status} />
          </li>
        ))}
      </ul>
    </div>
  )
}