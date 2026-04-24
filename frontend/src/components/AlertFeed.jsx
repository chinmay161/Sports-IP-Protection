// src/components/AlertFeed.jsx
import { useMemo, useState } from "react"

import { simulateAlert } from "../api/client.js"
import { useEventStream } from "../hooks/useEventStream.js"
import AlertCard from "./AlertCard.jsx"

const STATUS_DOT = {
  open: "bg-emerald-400",
  connecting: "bg-yellow-400 animate-pulse",
  closed: "bg-slate-500",
  error: "bg-red-500",
}

const FILTERS = ["all", "open", "acknowledged", "dmca_initiated", "resolved"]

export default function AlertFeed() {
  const { alerts, connectionStatus, error, replaceAlert, refresh } = useEventStream()
  const [filter, setFilter] = useState("all")
  const [simulating, setSimulating] = useState(false)

  const visible = useMemo(() => {
    if (filter === "all") return alerts
    return alerts.filter((a) => a.status === filter)
  }, [alerts, filter])

  const handleSimulate = async () => {
    setSimulating(true)
    try {
      await simulateAlert()
      // The WebSocket will deliver the new alert; no manual refresh needed.
    } catch (exc) {
      console.error("simulate_failed", exc)
    } finally {
      setSimulating(false)
    }
  }

  return (
    <section className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-100">Alert feed</h1>

        <div className="flex items-center gap-2 rounded-full border border-slate-800 bg-slate-900 px-3 py-1 text-xs">
          <span className={`h-2 w-2 rounded-full ${STATUS_DOT[connectionStatus] ?? STATUS_DOT.closed}`} />
          <span className="text-slate-300 capitalize">{connectionStatus}</span>
        </div>

        <span className="text-xs text-slate-500">
          {visible.length} / {alerts.length} shown
        </span>

        <div className="ml-auto flex items-center gap-2">
          <select
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
          >
            {FILTERS.map((f) => (
              <option key={f} value={f}>
                {f === "all" ? "All statuses" : f.replace("_", " ")}
              </option>
            ))}
          </select>

          <button
            onClick={refresh}
            className="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-200 hover:border-slate-500"
          >
            Refresh
          </button>

          {import.meta.env.DEV && (
            <button
              onClick={handleSimulate}
              disabled={simulating}
              className="rounded-md bg-cyan-500 px-3 py-1 text-xs font-semibold text-slate-950 hover:bg-cyan-400 disabled:opacity-50"
            >
              {simulating ? "..." : "Simulate alert"}
            </button>
          )}
        </div>
      </header>

      {error && (
        <p className="mx-6 mt-4 rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          {error}
        </p>
      )}

      <div className="flex-1 space-y-3 overflow-y-auto p-6">
        {visible.length === 0 ? (
          <div className="flex h-full items-center justify-center text-sm text-slate-500">
            {alerts.length === 0
              ? "No alerts yet. The feed is listening."
              : "No alerts match this filter."}
          </div>
        ) : (
          visible.map((a) => (
            <AlertCard key={a.id} alert={a} onReplace={replaceAlert} />
          ))
        )}
      </div>
    </section>
  )
}