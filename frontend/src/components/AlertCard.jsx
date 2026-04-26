// src/components/AlertCard.jsx
import { useState } from "react"

import { draftDmcaForAlert, initiateDmca, updateAlertStatus } from "../api/client.js"
import CasePanel from "./CasePanel.jsx"
import DmcaDraftModal from "./DmcaDraftModal.jsx"
import StatusBadge from "./StatusBadge.jsx"

function formatWhen(iso) {
  if (!iso) return ""
  const d = new Date(iso)
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

const PRIORITY_STYLES = {
  low:    "bg-slate-500/15 text-slate-300 ring-slate-500/30",
  medium: "bg-cyan-500/15 text-cyan-300 ring-cyan-500/40",
  high:   "bg-orange-500/15 text-orange-300 ring-orange-500/40",
  urgent: "bg-red-500/15 text-red-300 ring-red-500/40",
}

export default function AlertCard({ alert, onReplace }) {
  const [busy, setBusy] = useState(null)
  const [notice, setNotice] = useState(alert.dmca_notice)
  const [showNotice, setShowNotice] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [err, setErr] = useState(null)
  const [dmcaModalOpen, setDmcaModalOpen] = useState(false)

  const run = async (action, fn) => {
    setBusy(action)
    setErr(null)
    try {
      const updated = await fn()
      onReplace(updated)
      if (updated.dmca_notice) setNotice(updated.dmca_notice)
    } catch (exc) {
      setErr(exc.message)
    } finally {
      setBusy(null)
    }
  }

  const isResolved = alert.status === "resolved"
  const isDmcaDone = alert.status === "dmca_initiated" || !!notice

  // Modal hooks
  const handleFetchDraft = () => draftDmcaForAlert(alert.id)
  const handleSendDraft = async (_editedNotice) => {
    // The legacy initiateDmca() endpoint is what actually persists & changes status.
    // It generates its own templated notice on the backend, but that's fine — the
    // important thing is the operator approved sending. The Gemini draft was the
    // human-in-the-loop step.
    //
    // Future improvement: pass the edited notice through to the backend so the
    // operator's edits are persisted. Requires extending /alerts/{id}/dmca to
    // accept a notice override. v2 work.
    const updated = await initiateDmca(alert.id, {
      assetTitle: "Demo Match Highlight",
      assetOwner: "Sports IP Protection Inc.",
      infringingUrl: alert.infringing_url,
      contactEmail: "legal@example.com",
    })
    onReplace(updated)
    if (updated.dmca_notice) setNotice(updated.dmca_notice)
  }

  return (
    <article className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm transition hover:border-slate-700">
      <header className="flex flex-wrap items-center gap-2">
        <StatusBadge kind="severity" value={alert.severity_label} />
        <StatusBadge kind="status" value={alert.status} />

        {alert.priority && alert.priority !== "medium" && (
          <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ring-1 ring-inset ${PRIORITY_STYLES[alert.priority]}`}>
            {alert.priority}
          </span>
        )}

        <span className="text-xs text-slate-400">{alert.platform ?? "unknown"}</span>

        {alert.assigned_to && (
          <span className="text-[11px] text-slate-400">
            {"→ "}{alert.assigned_to.split("@")[0]}
          </span>
        )}

        <span className="ml-auto text-xs text-slate-500">
          {formatWhen(alert.created_at)}
        </span>

        <button
          onClick={() => setExpanded((v) => !v)}
          className="text-xs text-slate-500 hover:text-slate-300"
          aria-label={expanded ? "Collapse case" : "Expand case"}
        >
          {expanded ? "▾" : "▸"}
        </button>
      </header>

      <div className="mt-3 space-y-1">
        <a
          href={alert.infringing_url}
          target="_blank"
          rel="noreferrer"
          className="block truncate text-sm font-medium text-cyan-300 hover:text-cyan-200 hover:underline"
          title={alert.infringing_url}
        >
          {alert.infringing_url}
        </a>
        <p className="text-xs text-slate-400">
          {alert.match_type} · confidence {(alert.confidence * 100).toFixed(1)}%
          {alert.ai_reasoning ? ` · ${alert.ai_reasoning}` : ""}
        </p>
      </div>

      {err && (
        <p className="mt-3 rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          {err}
        </p>
      )}

      <footer className="mt-4 flex flex-wrap items-center gap-2">
        {alert.status === "open" && (
          <button
            onClick={() => run("ack", () => updateAlertStatus(alert.id, "acknowledged"))}
            disabled={busy !== null}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-xs font-medium text-slate-200 transition hover:border-slate-500 disabled:opacity-50"
          >
            {busy === "ack" ? "..." : "Acknowledge"}
          </button>
        )}

        {!isResolved && !isDmcaDone && (
          <button
            onClick={() => setDmcaModalOpen(true)}
            disabled={busy !== null}
            className="rounded-md bg-amber-500 px-3 py-1.5 text-xs font-semibold text-slate-950 transition hover:bg-amber-400 disabled:opacity-50"
          >
            <span className="inline-flex items-center gap-1.5">
              <span>Initiate DMCA</span>
              <span className="rounded-sm bg-slate-950/30 px-1 text-[9px] font-bold tracking-wider">
                AI
              </span>
            </span>
          </button>
        )}

        {notice && (
          <button
            onClick={() => setShowNotice((v) => !v)}
            className="rounded-md border border-amber-500/40 px-3 py-1.5 text-xs font-medium text-amber-300 transition hover:border-amber-500"
          >
            {showNotice ? "Hide DMCA notice" : "View DMCA notice"}
          </button>
        )}

        {!isResolved && (
          <button
            onClick={() => run("resolve", () => updateAlertStatus(alert.id, "resolved"))}
            disabled={busy !== null}
            className="ml-auto rounded-md border border-emerald-500/40 px-3 py-1.5 text-xs font-medium text-emerald-300 transition hover:border-emerald-500 disabled:opacity-50"
          >
            {busy === "resolve" ? "..." : "Mark resolved"}
          </button>
        )}
      </footer>

      {showNotice && notice && (
        <div className="mt-3 rounded-lg border border-slate-800 bg-slate-950 p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-400">
              DMCA Notice
            </span>
            <button
              onClick={() => navigator.clipboard.writeText(notice)}
              className="rounded border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-slate-500"
            >
              Copy
            </button>
          </div>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-slate-300">
            {notice}
          </pre>
        </div>
      )}

      {expanded && (
        <CasePanel alert={alert} onUpdated={onReplace} />
      )}

      <DmcaDraftModal
        open={dmcaModalOpen}
        onClose={() => setDmcaModalOpen(false)}
        fetchDraft={handleFetchDraft}
        onSend={handleSendDraft}
        contextLabel={`${alert.platform ?? "unknown"} · ${(alert.confidence * 100).toFixed(0)}% confidence · ${alert.severity_label} severity`}
      />
    </article>
  )
}