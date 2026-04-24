// src/components/PropagationPage.jsx
import { useEffect, useState } from "react"

import {
  getAssetPropagationSummary,
  getPropagationGraph,
  getPropagationTimeline,
} from "../api/client.js"
import PropagationGraph from "./PropagationGraph.jsx"
import PropagationSummary from "./PropagationSummary.jsx"
import PropagationTimeline from "./PropagationTimeline.jsx"

const PLACEHOLDER_MATCH_ID = "demo-match-0001"
const PLACEHOLDER_ASSET_ID = "demo-asset-0001"

export default function PropagationPage() {
  const [graph, setGraph] = useState(null)
  const [timeline, setTimeline] = useState(null)
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    Promise.all([
      getPropagationGraph(PLACEHOLDER_MATCH_ID),
      getPropagationTimeline(PLACEHOLDER_MATCH_ID),
      getAssetPropagationSummary(PLACEHOLDER_ASSET_ID),
    ])
      .then(([g, t, s]) => {
        if (cancelled) return
        setGraph(g)
        setTimeline(t)
        setSummary(s)
      })
      .catch((exc) => {
        if (!cancelled) setError(exc.message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [])

  return (
    <section className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-100">Propagation</h1>
        <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300">
          Mock data
        </span>
        <span className="text-xs text-slate-500">
          Live data wires in once Dev 1's /propagation API is ready
        </span>
      </header>

      <div className="flex-1 space-y-6 overflow-y-auto p-6">
        {error && (
          <p className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}

        {loading ? (
          <div className="py-8 text-center text-sm text-slate-500">Loading propagation data...</div>
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