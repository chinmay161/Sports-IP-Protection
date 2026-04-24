// src/components/StatusPill.jsx
// Colored pill for asset/ingest statuses: pending | processing | ready | failed.

const STYLES = {
  pending: "bg-slate-500/15 text-slate-300 ring-slate-500/30",
  processing: "bg-amber-500/15 text-amber-300 ring-amber-500/40 animate-pulse",
  ready: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40",
  failed: "bg-red-500/15 text-red-300 ring-red-500/40",
}

const LABELS = {
  pending: "Pending",
  processing: "Processing",
  ready: "Ready",
  failed: "Failed",
}

export default function StatusPill({ label, value }) {
  const styles = STYLES[value] ?? STYLES.pending
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${styles}`}
      title={label}
    >
      <span className="text-[10px] uppercase tracking-wider opacity-70">
        {label}
      </span>
      <span className="font-semibold">{LABELS[value] ?? value}</span>
    </span>
  )
}