// src/components/StatusBadge.jsx
// Colored pill for severity labels or alert status.

const SEVERITY_STYLES = {
  critical: "bg-red-500/15 text-red-300 ring-red-500/40",
  high: "bg-orange-500/15 text-orange-300 ring-orange-500/40",
  medium: "bg-yellow-500/15 text-yellow-200 ring-yellow-500/40",
  low: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
}

const STATUS_STYLES = {
  open: "bg-cyan-500/15 text-cyan-300 ring-cyan-500/40",
  acknowledged: "bg-indigo-500/15 text-indigo-300 ring-indigo-500/40",
  dmca_initiated: "bg-amber-500/15 text-amber-300 ring-amber-500/40",
  resolved: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40",
}

const STATUS_LABELS = {
  open: "Open",
  acknowledged: "Acknowledged",
  dmca_initiated: "DMCA Sent",
  resolved: "Resolved",
}

export default function StatusBadge({ kind, value }) {
  const styles =
    kind === "severity"
      ? SEVERITY_STYLES[value] ?? SEVERITY_STYLES.low
      : STATUS_STYLES[value] ?? STATUS_STYLES.open

  const label =
    kind === "severity"
      ? value.toUpperCase()
      : STATUS_LABELS[value] ?? value

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ring-inset ${styles}`}
    >
      {label}
    </span>
  )
}