// src/components/CasesPage.jsx
import { useEffect, useMemo, useState } from "react"

import { listAlerts } from "../api/client.js"
import { useEventStream } from "../hooks/useEventStream.js"
import USERS from "../fixtures/users.json"
import StatusBadge from "./StatusBadge.jsx"

const PRIORITY_RANK = { urgent: 0, high: 1, medium: 2, low: 3 }
const SEVERITY_RANK = { critical: 0, high: 1, medium: 2, low: 3 }

const PRIORITY_STYLES = {
  low:    "bg-slate-500/15 text-slate-300 ring-slate-500/30",
  medium: "bg-cyan-500/15 text-cyan-300 ring-cyan-500/40",
  high:   "bg-orange-500/15 text-orange-300 ring-orange-500/40",
  urgent: "bg-red-500/15 text-red-300 ring-red-500/40",
}

function formatWhen(iso) {
  if (!iso) return ""
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  })
}

function isOverdue(alert) {
  if (!alert.due_date) return false
  if (alert.status === "resolved") return false
  return new Date(alert.due_date) < new Date()
}

function userLabel(email) {
  if (!email) return "Unassigned"
  const u = USERS.find((u) => u.email === email)
  return u ? u.name : email
}

function CaseRow({ alert, onOpen }) {
  const overdue = isOverdue(alert)
  return (
    <div
      onClick={() => onOpen(alert)}
      className="flex cursor-pointer items-center gap-3 rounded-lg border border-slate-800 bg-slate-950/60 px-3 py-2.5 transition hover:border-slate-700 hover:bg-slate-900"
    >
      <StatusBadge kind="severity" value={alert.severity_label} />
      <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ring-1 ring-inset ${PRIORITY_STYLES[alert.priority ?? "medium"]}`}>
        {alert.priority ?? "medium"}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-xs text-slate-200" title={alert.infringing_url}>
          {alert.infringing_url}
        </div>
        <div className="text-[11px] text-slate-500">
          {alert.platform ?? "unknown"} · {formatWhen(alert.created_at)}
        </div>
      </div>
      {alert.due_date && (
        <span className={`text-[11px] ${overdue ? "text-red-300 font-semibold" : "text-slate-400"}`}>
          {overdue ? "Overdue" : "Due"} {formatWhen(alert.due_date)}
        </span>
      )}
      <StatusBadge kind="status" value={alert.status} />
    </div>
  )
}

function AssigneeColumn({ user, alerts, onOpen, onlyOpen }) {
  const filtered = onlyOpen ? alerts.filter((a) => a.status !== "resolved") : alerts

  const stats = useMemo(() => {
    const out = { total: filtered.length, critical: 0, overdue: 0 }
    filtered.forEach((a) => {
      if (a.severity_label === "critical") out.critical++
      if (isOverdue(a)) out.overdue++
    })
    return out
  }, [filtered])

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="mb-3 flex items-start justify-between">
        <div>
          <div className="text-sm font-semibold text-slate-100">
            {user ? user.name : "Unassigned"}
          </div>
          <div className="text-[11px] text-slate-500">
            {user ? user.role : "No assignee"}
          </div>
        </div>
        <div className="flex items-center gap-3 text-[11px]">
          <span className="text-slate-300">{stats.total} cases</span>
          {stats.critical > 0 && <span className="text-red-300">{stats.critical} critical</span>}
          {stats.overdue > 0 && <span className="text-red-300">{stats.overdue} overdue</span>}
        </div>
      </div>

      {filtered.length === 0 ? (
        <div className="rounded border border-dashed border-slate-800 py-4 text-center text-xs text-slate-600">
          No cases.
        </div>
      ) : (
        <div className="space-y-2">
          {filtered
            .slice()
            .sort((a, b) => {
              // resolved last
              if ((a.status === "resolved") !== (b.status === "resolved")) {
                return a.status === "resolved" ? 1 : -1
              }
              const sevDiff = (SEVERITY_RANK[a.severity_label] ?? 9) - (SEVERITY_RANK[b.severity_label] ?? 9)
              if (sevDiff !== 0) return sevDiff
              const priDiff = (PRIORITY_RANK[a.priority] ?? 9) - (PRIORITY_RANK[b.priority] ?? 9)
              if (priDiff !== 0) return priDiff
              return new Date(b.created_at) - new Date(a.created_at)
            })
            .map((alert) => (
              <CaseRow key={alert.id} alert={alert} onOpen={onOpen} />
            ))}
        </div>
      )}
    </div>
  )
}

export default function CasesPage({ onNavigate }) {
  const { alerts: liveAlerts } = useEventStream()
  const [allAlerts, setAllAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [onlyOpen, setOnlyOpen] = useState(true)

  useEffect(() => {
    let cancelled = false
    listAlerts({ limit: 100 })
      .then((items) => {
        if (!cancelled) setAllAlerts(items)
      })
      .catch((exc) => !cancelled && setError(exc.message))
      .finally(() => !cancelled && setLoading(false))
    return () => { cancelled = true }
  }, [])

  // Merge live updates from useEventStream into the canonical list
  const merged = useMemo(() => {
    const byId = new Map(allAlerts.map((a) => [a.id, a]))
    liveAlerts.forEach((a) => byId.set(a.id, a))
    return Array.from(byId.values())
  }, [allAlerts, liveAlerts])

  // Group by assignee
  const groups = useMemo(() => {
    const byAssignee = new Map()
    // Seed all known users so empty-but-valid columns show up
    USERS.forEach((u) => byAssignee.set(u.email, []))
    byAssignee.set(null, []) // unassigned bucket

    merged.forEach((alert) => {
      const key = alert.assigned_to ?? null
      if (!byAssignee.has(key)) byAssignee.set(key, [])
      byAssignee.get(key).push(alert)
    })

    // Order columns: Unassigned first (most likely to need attention), then users
    // sorted by load (descending). User columns with zero cases are hidden when
    // we have lots of users — keeps the layout focused.
    const entries = [...byAssignee.entries()]
    const unassigned = entries.find(([k]) => k === null)
    const userEntries = entries
      .filter(([k]) => k !== null)
      .sort(([, aA], [, aB]) => aB.length - aA.length)

    return [unassigned, ...userEntries].filter(Boolean)
  }, [merged])

  const overallStats = useMemo(() => {
    const out = { total: 0, open: 0, critical: 0, overdue: 0, unassigned: 0 }
    merged.forEach((a) => {
      out.total++
      if (a.status !== "resolved") out.open++
      if (a.severity_label === "critical" && a.status !== "resolved") out.critical++
      if (isOverdue(a)) out.overdue++
      if (!a.assigned_to) out.unassigned++
    })
    return out
  }, [merged])

  const handleOpen = (alert) => {
    onNavigate?.("alerts")
    // We don't have alert deep-linking, but this gets the user to the right page
    // where they can find and expand the alert card.
  }

  return (
    <section className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-100">Cases</h1>

        <div className="flex items-center gap-3 text-xs">
          <span className="text-slate-300">{overallStats.open} open</span>
          {overallStats.critical > 0 && <span className="text-red-300">{overallStats.critical} critical</span>}
          {overallStats.overdue > 0 && <span className="text-red-300">{overallStats.overdue} overdue</span>}
          <span className="text-slate-500">·</span>
          <span className="text-slate-400">{overallStats.unassigned} unassigned</span>
        </div>

        <label className="ml-auto flex items-center gap-2 text-xs text-slate-300">
          <input
            type="checkbox"
            checked={onlyOpen}
            onChange={(e) => setOnlyOpen(e.target.checked)}
            className="h-3.5 w-3.5 accent-cyan-500"
          />
          Only show open
        </label>
      </header>

      <div className="flex-1 overflow-y-auto p-6">
        {error && (
          <p className="mb-4 rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}

        {loading ? (
          <div className="py-8 text-center text-sm text-slate-500">Loading cases...</div>
        ) : merged.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-800 p-12 text-center">
            <div className="text-sm text-slate-400">No alerts in the system yet.</div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
            {groups.map(([assigneeEmail, alerts]) => {
              const user = assigneeEmail ? USERS.find((u) => u.email === assigneeEmail) : null
              return (
                <AssigneeColumn
                  key={assigneeEmail ?? "unassigned"}
                  user={user}
                  alerts={alerts}
                  onOpen={handleOpen}
                  onlyOpen={onlyOpen}
                />
              )
            })}
          </div>
        )}
      </div>
    </section>
  )
}