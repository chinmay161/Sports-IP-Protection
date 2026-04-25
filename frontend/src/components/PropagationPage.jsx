// src/components/PropagationPage.jsx
import { useEffect, useMemo, useState } from "react"

import {
  getAssetPropagationSummary,
  getPropagationGraph,
  getPropagationTimeline,
  listDetections,
} from "../api/client.js"
import PropagationGraph from "./PropagationGraph.jsx"
import PropagationSummary from "./PropagationSummary.jsx"
import PropagationTimeline from "./PropagationTimeline.jsx"

const SEVERITY_RANK = { critical: 0, high: 1, medium: 2, low: 3 }


function formatWhen(iso) {
  if (!iso) return ""
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  })
}

export default function PropagationPage({ preselectedMatchId }) {
  // List of detections to populate the selector
  const [detections, setDetections] = useState([])
  const [detectionsLoading, setDetectionsLoading] = useState(true)
  const [detectionsError, setDetectionsError] = useState(null)

  // Currently selected match
  const [selectedMatchId, setSelectedMatchId] = useState(preselectedMatchId ?? null)

  // Propagation data for the selected match
  const [graph, setGraph] = useState(null)
  const [timeline, setTimeline] = useState(null)
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Fetch detections list once
  useEffect(() => {
    let cancelled = false
    listDetections({ limit: 50 })
      .then((res) => {
        if (cancelled) return
        // Sort by severity → recency for a sensible default ordering
        const sorted = [...(res.items ?? [])].sort((a, b) => {
          const sevDiff = (SEVERITY_RANK[a.severity] ?? 9) - (SEVERITY_RANK[b.severity] ?? 9)
          if (sevDiff !== 0) return sevDiff
          return new Date(b.detected_at) - new Date(a.detected_at)
        })
        setDetections(sorted)
        // Auto-select the first match so the page isn't blank
        if (sorted.length > 0) setSelectedMatchId(sorted[0].id)
      })
      .catch((exc) => !cancelled && setDetectionsError(exc.message))
      .finally(() => !cancelled && setDetectionsLoading(false))
    return () => { cancelled = true }
  }, [])

// React to deep-link selection from the Detections page
useEffect(() => {
  if (preselectedMatchId && preselectedMatchId !== selectedMatchId) {
    setSelectedMatchId(preselectedMatchId)
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [preselectedMatchId])

  // Fetch propagation data whenever the selection changes
  useEffect(() => {
    if (!selectedMatchId) {
      setGraph(null); setTimeline(null); setSummary(null)
      return
    }

    const detection = detections.find((d) => d.id === selectedMatchId)
    if (!detection) return

    let cancelled = false
    setLoading(true)
    setError(null)

    Promise.all([
      getPropagationGraph(selectedMatchId),
      getPropagationTimeline(selectedMatchId),
      getAssetPropagationSummary(detection.asset_id),
    ])
      .then(([g, t, s]) => {
        if (cancelled) return
        setGraph(g); setTimeline(t); setSummary(s)
      })
      .catch((exc) => !cancelled && setError(exc.message))
      .finally(() => !cancelled && setLoading(false))

    return () => { cancelled = true }
  }, [selectedMatchId, detections])

  const selectedDetection = useMemo(
    () => detections.find((d) => d.id === selectedMatchId),
    [detections, selectedMatchId],
  )

  const renderSelectorBody = () => {
    if (detectionsLoading) return <span className="text-xs text-slate-500">Loading detections...</span>
    if (detectionsError)   return <span className="text-xs text-red-300">Error: {detectionsError}</span>
    if (detections.length === 0) {
      return (
        <span className="text-xs text-slate-500">
          No matches yet. Run a scan from the Assets page to populate detections.
        </span>
      )
    }
    return (
      <select
        value={selectedMatchId ?? ""}
        onChange={(e) => setSelectedMatchId(e.target.value)}
        className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-200 focus:border-slate-500 focus:outline-none"
      >
        {detections.map((d) => (
          <option key={d.id} value={d.id}>
            [{d.severity}] {d.platform} · {d.source_channel ?? "(unknown)"} · {(d.confidence * 100).toFixed(0)}% · {formatWhen(d.detected_at)}
          </option>
        ))}
      </select>
    )
  }

  return (
    <section className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-100">Propagation</h1>
        <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-emerald-300">
          Live
        </span>
        <div className="ml-auto flex items-center gap-2">
          {renderSelectorBody()}
        </div>
      </header>

      <div className="flex-1 space-y-6 overflow-y-auto p-6">
        {error && (
          <p className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}

        {!selectedMatchId && !detectionsLoading && detections.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-800 p-12 text-center">
            <div className="text-sm text-slate-400">No detection matches yet.</div>
            <div className="mt-2 text-xs text-slate-500">
              When a scan finds an infringement, it appears here with a propagation graph showing
              how the content spread across platforms.
            </div>
          </div>
        ) : loading ? (
          <div className="py-8 text-center text-sm text-slate-500">
            Loading propagation data for {selectedDetection?.platform} match...
          </div>
        ) : (
          <>
            <PropagationSummary summary={summary} />
            <PropagationTimeline timeline={timeline} />
            <PropagationGraph graph={graph} />
          </>
        )}
      </div>
    </section>
  )
}
