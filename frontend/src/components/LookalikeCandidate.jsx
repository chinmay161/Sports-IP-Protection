// src/components/LookalikeCandidate.jsx
import { useState } from "react"

import { dismissVisualCandidate } from "../api/client.js"

const PLATFORM_DOT = {
  youtube:  "bg-red-400",
  tiktok:   "bg-cyan-400",
  telegram: "bg-blue-400",
  web:      "bg-purple-400",
  unknown:  "bg-slate-500",
}

function ScoreBadge({ label, value, format = "percent", className = "" }) {
  const display = format === "percent" ? `${(value * 100).toFixed(0)}%` : String(value)
  return (
    <div className={`rounded-md border border-slate-700 bg-slate-900/60 px-2 py-1 ${className}`}>
      <div className="text-[9px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="text-xs font-semibold text-slate-200">{display}</div>
    </div>
  )
}

export default function LookalikeCandidate({ candidate, onDismissed, onCompare }) {
  const [imgError, setImgError] = useState(false)
  const [dismissing, setDismissing] = useState(false)
  const [error, setError] = useState(null)

  const handleDismiss = async (e) => {
    e.stopPropagation()
    if (!confirm("Dismiss this candidate? This cannot be undone.")) return
    setDismissing(true)
    setError(null)
    try {
      await dismissVisualCandidate(candidate.id)
      onDismissed?.(candidate.id)
    } catch (exc) {
      setError(exc.message)
      setDismissing(false)
    }
  }

  const handleCompare = (e) => {
  e.stopPropagation()
  console.log("handleCompare called", { onCompare, candidate })
  onCompare?.(candidate)
}

  const score = candidate.visual_score
  const scoreColor =
    score >= 0.8 ? "bg-red-500/15 text-red-300 border-red-500/40" :
    score >= 0.65 ? "bg-orange-500/15 text-orange-300 border-orange-500/40" :
    score >= 0.5 ? "bg-yellow-500/15 text-yellow-300 border-yellow-500/40" :
    "bg-slate-500/15 text-slate-400 border-slate-500/40"

  return (
    <article className="overflow-hidden rounded-xl border border-slate-800 bg-slate-900/60 transition hover:border-slate-700">
      {/* Thumbnail (clickable to compare) */}
      <button
        onClick={handleCompare}
        className="relative block aspect-video w-full overflow-hidden bg-slate-950 hover:opacity-90"
      >
        {!imgError && candidate.thumbnail_url ? (
          <img
            src={candidate.thumbnail_url}
            alt={`Candidate ${candidate.platform}`}
            onError={() => setImgError(true)}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center text-xs text-slate-600">
            Thumbnail unavailable
          </div>
        )}

        <div className={`absolute top-2 left-2 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${scoreColor}`}>
          {(score * 100).toFixed(0)}% match
        </div>

        <div className="absolute top-2 right-2 flex items-center gap-1.5 rounded-full bg-slate-950/80 px-2 py-0.5 text-[10px] font-medium text-slate-200 backdrop-blur">
          <span className={`h-1.5 w-1.5 rounded-full ${PLATFORM_DOT[candidate.platform] ?? PLATFORM_DOT.unknown}`} />
          {candidate.platform}
        </div>

        <div className="absolute bottom-2 right-2 rounded bg-slate-950/80 px-2 py-0.5 text-[10px] font-medium text-cyan-300 backdrop-blur opacity-0 transition group-hover:opacity-100">
          Click to compare →
        </div>
      </button>

      {/* Body */}
      <div className="p-3">
        <a
          href={candidate.source_url}
          target="_blank"
          rel="noreferrer"
          className="block truncate text-xs text-cyan-300 hover:text-cyan-200 hover:underline"
          title={candidate.source_url}
        >
          {candidate.source_url}
        </a>

        <div className="mt-2 grid grid-cols-2 gap-1">
          <ScoreBadge
            label="pHash dist"
            value={candidate.phash_distance ?? "—"}
            format="raw"
          />
          {candidate.clip_score != null ? (
            <ScoreBadge label="CLIP" value={candidate.clip_score} format="percent" />
          ) : (
            <div className="rounded-md border border-dashed border-slate-700 px-2 py-1">
              <div className="text-[9px] uppercase tracking-wider text-slate-600">CLIP</div>
              <div className="text-xs text-slate-600">phash only</div>
            </div>
          )}
        </div>

        {error && (
          <p className="mt-2 rounded border border-red-500/40 bg-red-500/10 px-2 py-1 text-[10px] text-red-300">
            {error}
          </p>
        )}

        <div className="mt-2 grid grid-cols-2 gap-1">
          <button
            onClick={handleCompare}
            className="rounded-md bg-cyan-500/90 px-2 py-1 text-[11px] font-semibold text-slate-950 hover:bg-cyan-400"
          >
            Compare
          </button>
          <button
            onClick={handleDismiss}
            disabled={dismissing}
            className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-400 transition hover:border-red-500/50 hover:text-red-300 disabled:opacity-50"
          >
            {dismissing ? "Dismissing..." : "Dismiss"}
          </button>
        </div>
      </div>
    </article>
  )
}