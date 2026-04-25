// src/components/SystemPage.jsx
import { useCallback, useEffect, useState } from "react"

import { getHealth } from "../api/client.js"
import { useEventStream } from "../hooks/useEventStream.js"

const STATUS_DOT_BG = {
  green: "bg-emerald-400",
  yellow: "bg-yellow-400 animate-pulse",
  red: "bg-red-500",
  gray: "bg-slate-500",
}

const STATUS_LABEL = {
  green: "Healthy",
  yellow: "Degraded",
  red: "Down",
  gray: "Unknown",
}

function StatusRow({ label, status, detail, secondary }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-slate-800/60 py-3 last:border-b-0">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${STATUS_DOT_BG[status] ?? STATUS_DOT_BG.gray}`} />
          <span className="text-sm font-medium text-slate-100">{label}</span>
          <span className="text-[11px] text-slate-500">{STATUS_LABEL[status] ?? "Unknown"}</span>
        </div>
        {detail && <div className="mt-1 ml-4 text-xs text-slate-400">{detail}</div>}
      </div>
      {secondary && (
        <div className="shrink-0 text-right text-[11px] font-mono text-slate-500">{secondary}</div>
      )}
    </div>
  )
}

function Section({ title, children }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
        {title}
      </div>
      <div className="divide-y divide-slate-800/60">{children}</div>
    </div>
  )
}

export default function SystemPage() {
  const { connectionStatus } = useEventStream()
  const [health, setHealth] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)

  const fetchHealth = useCallback(async () => {
    try {
      const h = await getHealth()
      setHealth(h)
      setError(null)
    } catch (exc) {
      setError(exc.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchHealth()
    // Re-poll every 10 seconds to keep status current
    const interval = setInterval(fetchHealth, 10_000)
    return () => clearInterval(interval)
  }, [fetchHealth])

  // Map raw health response to per-service statuses
  const milvusStatus =
    health?.milvus === "ready" ? "green" : health?.milvus === "unavailable" ? "red" : "gray"
  const apiStatus = health ? "green" : error ? "red" : "gray"
  const wsStatus =
    connectionStatus === "open" ? "green" :
    connectionStatus === "connecting" ? "yellow" :
    connectionStatus === "error" ? "red" : "gray"

  return (
    <section className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-100">System</h1>
        <span className="text-xs text-slate-500">
          Service health and configuration
        </span>
        <button
          onClick={fetchHealth}
          className="ml-auto rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-200 hover:border-slate-500"
        >
          Refresh
        </button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-6">
        {error && (
          <p className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}

        <Section title="Core services">
          <StatusRow
            label="API server"
            status={apiStatus}
            detail={health ? "FastAPI on http://127.0.0.1:8001" : "Not reachable"}
            secondary={health ? "uvicorn" : "—"}
          />
          <StatusRow
            label="WebSocket events"
            status={wsStatus}
            detail={`Real-time event stream · ${connectionStatus}`}
            secondary="ws://.../ws/events"
          />
          <StatusRow
            label="Vector database"
            status={milvusStatus}
            detail={
              health?.milvus === "ready"
                ? "Milvus collection ready for fingerprint queries"
                : health?.milvus_error || "Connect failed — start Docker Desktop"
            }
            secondary="Milvus 2.3"
          />
        </Section>

        <Section title="Background workers">
          <StatusRow
            label="Celery worker"
            status="gray"
            detail="Status not exposed via HTTP. Check the worker terminal."
            secondary="redis://localhost:6379/0"
          />
          <StatusRow
            label="Redis pub/sub"
            status={wsStatus === "open" ? "green" : "gray"}
            detail="Used for asset.status_changed, alert.created, alert.updated"
            secondary="redis://localhost:6379/2"
          />
        </Section>

        <Section title="Configuration">
          <StatusRow
            label="Authentication"
            status="yellow"
            detail="Auth0 disabled in dev mode (AUTH_DISABLED=true)"
            secondary="dev mode"
          />
          <StatusRow
            label="Storage backend"
            status="gray"
            detail="MinIO/S3 not configured. Local media_store/ used for uploads."
            secondary="local fs"
          />
          <StatusRow
            label="GeoIP database"
            status="gray"
            detail="Not configured. Match.geo_country populated from seed data only."
            secondary="MaxMind"
          />
        </Section>

        <Section title="Build info">
          <StatusRow
            label="Frontend"
            status="green"
            detail="React 19 · Vite · Tailwind v4"
            secondary={import.meta.env?.MODE ?? "dev"}
          />
          <StatusRow
            label="Backend"
            status={health ? "green" : "gray"}
            detail="FastAPI · SQLAlchemy 2 · Celery · Pydantic v2"
            secondary="Python 3.12"
          />
          <StatusRow
            label="Database"
            status="green"
            detail="SQLite (dev). PostgreSQL planned for production."
            secondary="sqlite+aiosqlite"
          />
        </Section>

        {loading && (
          <div className="text-center text-xs text-slate-500">Refreshing...</div>
        )}
      </div>
    </section>
  )
}