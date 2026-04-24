// src/components/DashboardPage.jsx
import { useCallback, useEffect, useRef, useState } from "react"

import { getDashboardStats } from "../api/client.js"
import { useEventStream } from "../hooks/useEventStream.js"
import AlertsOverTime from "./dashboard/AlertsOverTime.jsx"
import KpiTiles from "./dashboard/KpiTiles.jsx"
import PlatformBreakdown from "./dashboard/PlatformBreakdown.jsx"
import PriorityQueue from "./dashboard/PriorityQueue.jsx"

const STATUS_DOT = {
  open: "bg-emerald-400",
  connecting: "bg-yellow-400 animate-pulse",
  closed: "bg-slate-500",
  error: "bg-red-500",
}

const WINDOW_DAYS = 7
const REFETCH_DEBOUNCE_MS = 1500

export default function DashboardPage({ onNavigate }) {
  const { alerts, connectionStatus } = useEventStream()

  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const debounceTimerRef = useRef(null)

  const fetchStats = useCallback(async () => {
    try {
      const s = await getDashboardStats({ windowDays: WINDOW_DAYS })
      setStats(s)
      setError(null)
    } catch (exc) {
      setError(exc.message)
    } finally {
      setLoading(false)
    }
  }, [])

  // Initial + manual refresh
  useEffect(() => {
    fetchStats()
  }, [fetchStats])

  // Event-driven refresh. `alerts` from useEventStream changes on every
  // alert.created / alert.updated WebSocket message. We debounce so a burst
  // of simulated alerts only triggers one refetch.
  useEffect(() => {
    if (loading) return // skip during initial load
    if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    debounceTimerRef.current = setTimeout(fetchStats, REFETCH_DEBOUNCE_MS)
    return () => {
      if (debounceTimerRef.current) clearTimeout(debounceTimerRef.current)
    }
  }, [alerts.length, fetchStats, loading])

  return (
    <section className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-100">Dashboard</h1>

        <div className="flex items-center gap-2 rounded-full border border-slate-800 bg-slate-900 px-3 py-1 text-xs">
          <span className={`h-2 w-2 rounded-full ${STATUS_DOT[connectionStatus] ?? STATUS_DOT.closed}`} />
          <span className="capitalize text-slate-300">{connectionStatus}</span>
        </div>

        {stats?.generated_at && (
          <span className="text-xs text-slate-500">
            Updated {new Date(stats.generated_at).toLocaleTimeString()}
          </span>
        )}

        <button
          onClick={fetchStats}
          className="ml-auto rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-200 hover:border-slate-500"
        >
          Refresh
        </button>
      </header>

      <div className="flex-1 space-y-6 overflow-y-auto p-6">
        {error && (
          <p className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}

        {loading ? (
          <div className="py-8 text-center text-sm text-slate-500">Loading dashboard...</div>
        ) : !stats ? (
          <div className="py-8 text-center text-sm text-slate-500">No data.</div>
        ) : (
          <>
            <KpiTiles kpis={stats.kpis} />

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
              <div className="lg:col-span-2">
                <AlertsOverTime data={stats.timeseries} windowDays={stats.time_window_days} />
              </div>
              <div>
                <PlatformBreakdown platforms={stats.top_platforms} />
              </div>
            </div>

            <PriorityQueue
              items={stats.priority_queue}
              onGoToAlerts={onNavigate ? () => onNavigate("alerts") : undefined}
            />
          </>
        )}
      </div>
    </section>
  )
}