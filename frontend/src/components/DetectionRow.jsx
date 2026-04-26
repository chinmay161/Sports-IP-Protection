// src/components/DetectionRow.jsx
import { useState } from "react"

import { draftDmcaForDetection } from "../api/client.js"
import DmcaDraftModal from "./DmcaDraftModal.jsx"
import StatusBadge from "./StatusBadge.jsx"

const PLATFORM_DOT = {
  youtube:  "bg-red-400",
  tiktok:   "bg-cyan-400",
  telegram: "bg-blue-400",
  web:      "bg-purple-400",
  unknown:  "bg-slate-500",
}

function formatWhen(iso) {
  if (!iso) return ""
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  })
}

function formatDurationMs(ms) {
  if (!ms) return ""
  const sec = ms / 1000
  if (sec < 60) return `${sec.toFixed(0)}s`
  const min = sec / 60
  if (min < 60) return `${min.toFixed(0)}m`
  const hr = min / 60
  return `${hr.toFixed(1)}h`
}

function formatViews(n) {
  if (n == null) return "—"
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return n.toLocaleString()
}

export default function DetectionRow({ detection, onViewPropagation }) {
  const [dmcaOpen, setDmcaOpen] = useState(false)

  const handleDraft = () => draftDmcaForDetection(detection.id)

  // For detections we don't have a "send and persist" backend flow that takes
  // an edited notice — the existing /detections/{id}/dmca only flips status.
  // For demo purposes we acknowledge the action and close. Adding a real
  // override-aware send is v2 work.
  const handleSend = async (_editedNotice) => {
    // No-op send — UX feedback only. The modal closes after a brief delay
    // so the operator sees the "Sent" confirmation.
    await new Promise((resolve) => setTimeout(resolve, 400))
  }

  const handleOpenDmca = (e) => {
    e.stopPropagation()
    setDmcaOpen(true)
  }

  return (
    <>
      <article
        onClick={() => onViewPropagation?.(detection)}
        className="cursor-pointer rounded-xl border border-slate-800 bg-slate-900/60 p-4 shadow-sm transition hover:border-slate-700 hover:bg-slate-900"
      >
        <header className="flex flex-wrap items-center gap-2">
          <StatusBadge kind="severity" value={detection.severity} />
          <span className="flex items-center gap-1.5 text-xs text-slate-300">
            <span className={`h-1.5 w-1.5 rounded-full ${PLATFORM_DOT[detection.platform] ?? PLATFORM_DOT.unknown}`} />
            {detection.platform}
          </span>
          <span className="text-xs text-slate-400">
            {detection.source_channel ?? "(unknown channel)"}
          </span>
          <span className="ml-auto text-xs text-slate-500">
            {formatWhen(detection.detected_at)}
          </span>
        </header>

        <div className="mt-2">
          <a
            href={detection.source_url}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="block truncate text-sm text-cyan-300 hover:text-cyan-200 hover:underline"
            title={detection.source_url}
          >
            {detection.source_url}
          </a>
        </div>

        <footer className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-slate-400">
          <span>
            confidence <span className="font-semibold text-slate-200">{(detection.confidence * 100).toFixed(0)}%</span>
          </span>
          <span>
            views <span className="font-semibold text-slate-200">{formatViews(detection.view_count)}</span>
          </span>
          <span>
            duration <span className="font-semibold text-slate-200">{formatDurationMs(detection.duration_matched_ms)}</span>
          </span>
          {detection.geo_country && (
            <span>
              geo <span className="font-semibold text-slate-200">{detection.geo_country}</span>
            </span>
          )}

          <button
            onClick={handleOpenDmca}
            className="ml-auto inline-flex items-center gap-1.5 rounded-md border border-amber-500/40 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-amber-300 transition hover:border-amber-500"
          >
            DMCA
            <span className="rounded-sm bg-amber-500/20 px-1 text-[9px] font-bold tracking-wider">AI</span>
          </button>

          <span className="text-cyan-400 hover:text-cyan-300">
            View propagation →
          </span>
        </footer>
      </article>

      <DmcaDraftModal
        open={dmcaOpen}
        onClose={() => setDmcaOpen(false)}
        fetchDraft={handleDraft}
        onSend={handleSend}
        contextLabel={`${detection.platform} · ${detection.source_channel ?? "(unknown)"} · ${(detection.confidence * 100).toFixed(0)}% confidence`}
      />
    </>
  )
}