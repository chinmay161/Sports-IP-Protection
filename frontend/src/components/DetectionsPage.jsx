// src/components/DetectionsPage.jsx
import { useCallback, useEffect, useMemo, useState } from "react"

import { listDetections } from "../api/client.js"
import DetectionRow from "./DetectionRow.jsx"

const SEVERITY_RANK = { critical: 0, high: 1, medium: 2, low: 3 }
const PLATFORMS = ["all", "youtube", "tiktok", "telegram", "web"]
const SEVERITIES = ["all", "critical", "high", "medium", "low"]

export default function DetectionsPage({ onNavigate, onSelectMatch }) {
  const [detections, setDetections] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [platformFilter, setPlatformFilter] = useState("all")
  const [severityFilter, setSeverityFilter] = useState("all")

  const fetchDetections = useCallback(async () => {
    try {
      const res = await listDetections({ limit: 100 })
      setDetections(res.items ?? [])
      setError(null)
    } catch (exc) {
      setError(exc.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchDetections()
  }, [fetchDetections])

  const filtered = useMemo(() => {
    let items = [...detections]
    if (platformFilter !== "all") items = items.filter((d) => d.platform === platformFilter)
    if (severityFilter !== "all") items = items.filter((d) => d.severity === severityFilter)
    items.sort((a, b) => {
      const sev = (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9)
      if (sev !== 0) return sev
      return new Date(b.detected_at) - new Date(a.detected_at)
    })
    return items
  }, [detections, platformFilter, severityFilter])

  const counts = useMemo(() => {
    const out = { critical: 0, high: 0, medium: 0, low: 0 }
    detections.forEach((d) => {
      if (out[d.severity] !== undefined) out[d.severity]++
    })
    return out
  }, [detections])

  const handleViewPropagation = (detection) => {
    onSelectMatch?.(detection.id)
    onNavigate?.("propagation")
  }

  return (
    <section className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-100">Detections</h1>

        <div className="flex items-center gap-3 text-xs">
          {counts.critical > 0 && <span className="text-red-300">{counts.critical} critical</span>}
          {counts.high > 0 && <span className="text-orange-300">{counts.high} high</span>}
          {counts.medium > 0 && <span className="text-yellow-300">{counts.medium} medium</span>}
          {counts.low > 0 && <span className="text-slate-400">{counts.low} low</span>}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <select
            value={platformFilter}
            onChange={(e) => setPlatformFilter(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
          >
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>{p === "all" ? "All platforms" : p}</option>
            ))}
          </select>
          <select
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
          >
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>{s === "all" ? "All severities" : s}</option>
            ))}
          </select>
          <button
            onClick={fetchDetections}
            className="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-200 hover:border-slate-500"
          >
            Refresh
          </button>
        </div>
      </header>

      <div className="flex-1 space-y-3 overflow-y-auto p-6">
        {error && (
          <p className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}

        {loading ? (
          <div className="py-8 text-center text-sm text-slate-500">Loading detections...</div>
        ) : filtered.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-800 p-12 text-center">
            <div className="text-sm text-slate-400">
              {detections.length === 0
                ? "No detections yet."
                : "No detections match the current filters."}
            </div>
            {detections.length === 0 && (
              <div className="mt-2 text-xs text-slate-500">
                Run a scan from the Assets page to populate detections.
              </div>
            )}
          </div>
        ) : (
          filtered.map((d) => (
            <DetectionRow
              key={d.id}
              detection={d}
              onViewPropagation={handleViewPropagation}
            />
          ))
        )}
      </div>
    </section>
  )
}
