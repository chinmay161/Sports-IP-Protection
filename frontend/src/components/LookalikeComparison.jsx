// src/components/LookalikeComparison.jsx
import { useEffect, useState } from "react"

import {
  dismissVisualCandidate,
  getAssetFrameImageUrl,
  listAssetFrames,
} from "../api/client.js"

const PLATFORM_DOT = {
  youtube:  "bg-red-400",
  tiktok:   "bg-cyan-400",
  telegram: "bg-blue-400",
  web:      "bg-purple-400",
  unknown:  "bg-slate-500",
}

function formatTimestamp(ms) {
  const totalSeconds = Math.floor(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${seconds.toString().padStart(2, "0")}`
}

// --- Score visualization helpers --------------------------------------------

function PhashBar({ distance, threshold = 18 }) {
  // Lower distance = more similar. Visualize as filled bar from 0 to threshold.
  const pct = Math.max(0, Math.min(100, ((threshold - distance) / threshold) * 100))
  const color =
    distance <= 5  ? "bg-red-500" :
    distance <= 10 ? "bg-orange-500" :
    distance <= 14 ? "bg-yellow-500" :
                     "bg-slate-500"
  return (
    <div>
      <div className="flex justify-between text-[10px] text-slate-500">
        <span>Hamming distance</span>
        <span className="font-semibold text-slate-200">{distance ?? "—"} / {threshold}</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div className={`h-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function ClipBar({ score }) {
  if (score == null) {
    return (
      <div>
        <div className="flex justify-between text-[10px] text-slate-500">
          <span>CLIP cosine similarity</span>
          <span className="text-slate-600">phash-only mode</span>
        </div>
        <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-800">
          <div className="h-full w-0 bg-slate-700" />
        </div>
      </div>
    )
  }
  // CLIP cosine score is in roughly [-1, 1]; map to [0, 100].
  const pct = Math.max(0, Math.min(100, ((score + 1) / 2) * 100))
  const color =
    score >= 0.85 ? "bg-red-500" :
    score >= 0.7  ? "bg-orange-500" :
    score >= 0.5  ? "bg-yellow-500" :
                    "bg-slate-500"
  return (
    <div>
      <div className="flex justify-between text-[10px] text-slate-500">
        <span>CLIP cosine similarity</span>
        <span className="font-semibold text-slate-200">{(score * 100).toFixed(1)}%</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-800">
        <div className={`h-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

// --- Main component --------------------------------------------------------

export default function LookalikeComparison({ asset, candidate, onClose, onDismissed }) {
  const [frames, setFrames] = useState([])
  const [framesLoading, setFramesLoading] = useState(true)
  const [framesError, setFramesError] = useState(null)
  const [busy, setBusy] = useState(false)

  // Fetch the asset's frames once when the modal opens.
  useEffect(() => {
    if (!asset?.id) return
    let cancelled = false
    listAssetFrames(asset.id)
      .then((res) => {
        if (cancelled) return
        setFrames(res.items ?? [])
      })
      .catch((exc) => !cancelled && setFramesError(exc.message))
      .finally(() => !cancelled && setFramesLoading(false))
    return () => { cancelled = true }
  }, [asset?.id])

  // ESC closes the modal.
  useEffect(() => {
    const handler = (e) => e.key === "Escape" && onClose()
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [onClose])

  if (!candidate) return null

  const handleDismiss = async () => {
    if (!confirm("Dismiss this candidate as a false positive?")) return
    setBusy(true)
    try {
      await dismissVisualCandidate(candidate.id)
      onDismissed?.(candidate.id)
      onClose()
    } catch (exc) {
      alert(`Dismiss failed: ${exc.message}`)
      setBusy(false)
    }
  }

  const handleDmca = () => {
    // TODO: real DMCA flow once /visual/candidates/{id}/dmca exists.
    // For now, surface that the action was acknowledged.
    alert(
      "DMCA notice queued for this lookalike candidate. (v2 will wire the real workflow — " +
      "for now this is a placeholder action so the demo flow is complete.)",
    )
  }

  return (
    <div
      onClick={onClose}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 shadow-2xl"
      >
        {/* Header */}
        <header className="flex items-center justify-between border-b border-slate-800 px-6 py-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-100">Side-by-side comparison</h2>
            <p className="text-xs text-slate-500">
              Reviewing visual lookalike candidate against your protected asset.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:border-slate-500"
          >
            Close (Esc)
          </button>
        </header>

        {/* Body — three columns: asset / scoring / candidate */}
        <div className="grid flex-1 grid-cols-1 gap-px overflow-hidden bg-slate-800 lg:grid-cols-[2fr_1fr_2fr]">
          {/* --- LEFT: asset --- */}
          <section className="flex flex-col gap-3 overflow-y-auto bg-slate-900 p-5">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-cyan-400">
                Your asset
              </div>
              <div className="mt-1 truncate text-sm font-semibold text-slate-100" title={asset?.title}>
                {asset?.title ?? "Unknown asset"}
              </div>
              <div className="mt-0.5 truncate font-mono text-[10px] text-slate-500">
                {asset?.id}
              </div>
            </div>

            <div>
              <div className="text-[10px] uppercase tracking-wider text-slate-500">
                Extracted frames
                <span className="ml-1 text-slate-400">({frames.length})</span>
              </div>
              {framesLoading ? (
                <div className="mt-2 text-xs text-slate-500">Loading frames...</div>
              ) : framesError ? (
                <div className="mt-2 text-xs text-red-300">{framesError}</div>
              ) : frames.length === 0 ? (
                <div className="mt-2 text-xs text-slate-500">
                  No frames stored. The asset may not have been visually indexed yet.
                </div>
              ) : (
                <div className="mt-2 grid grid-cols-3 gap-1.5">
                  {frames.slice(0, 12).map((f) => (
                    <div
                      key={f.id}
                      className="relative overflow-hidden rounded border border-slate-800 bg-slate-950"
                    >
                      <div className="aspect-video">
                        <img
                          src={getAssetFrameImageUrl(asset.id, f.id)}
                          alt={`Frame at ${formatTimestamp(f.timestamp_ms)}`}
                          className="h-full w-full object-cover"
                          onError={(e) => {
                            e.target.style.display = "none"
                            e.target.nextSibling.style.display = "flex"
                          }}
                        />
                        <div className="hidden h-full w-full items-center justify-center text-[9px] text-slate-600">
                          (frame missing)
                        </div>
                      </div>
                      <div className="absolute bottom-0 right-0 rounded-tl bg-slate-950/80 px-1 py-0.5 text-[9px] font-mono text-slate-300">
                        {formatTimestamp(f.timestamp_ms)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </section>

          {/* --- CENTER: scoring --- */}
          <section className="flex flex-col gap-4 overflow-y-auto bg-slate-900 p-5">
            <div>
              <div className="text-[10px] font-semibold uppercase tracking-wider text-orange-400">
                Match scoring
              </div>
            </div>

            <div className="rounded-lg border border-slate-800 bg-slate-950 p-4 text-center">
              <div className="text-[10px] uppercase tracking-wider text-slate-500">
                Visual score
              </div>
              <div className="mt-1 text-3xl font-bold text-slate-100">
                {(candidate.visual_score * 100).toFixed(1)}<span className="text-lg text-slate-400">%</span>
              </div>
              <div className="mt-1 text-[10px] text-slate-500">
                Combined pHash + CLIP
              </div>
            </div>

            <div className="space-y-3">
              <PhashBar distance={candidate.phash_distance} />
              <ClipBar score={candidate.clip_score} />
            </div>

            <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-500">
                Discovered
              </div>
              <div className="mt-1 text-xs text-slate-300">
                {new Date(candidate.discovered_at).toLocaleString()}
              </div>
            </div>

            <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-500">
                Methodology
              </div>
              <p className="mt-1 text-[11px] leading-relaxed text-slate-400">
                Each asset frame is hashed (pHash) and embedded (CLIP).
                Candidates are scored against the closest frame match.
                Lower hamming distance = stronger visual identity match.
              </p>
            </div>
          </section>

          {/* --- RIGHT: candidate --- */}
          <section className="flex flex-col gap-3 overflow-y-auto bg-slate-900 p-5">
            <div>
              <div className="flex items-center gap-2">
                <div className="text-[10px] font-semibold uppercase tracking-wider text-red-400">
                  Lookalike candidate
                </div>
                <span className="flex items-center gap-1 rounded-full bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-300">
                  <span className={`h-1.5 w-1.5 rounded-full ${PLATFORM_DOT[candidate.platform] ?? PLATFORM_DOT.unknown}`} />
                  {candidate.platform}
                </span>
              </div>
            </div>

            <div className="overflow-hidden rounded-lg border border-slate-800 bg-slate-950">
              <div className="aspect-video">
                {candidate.thumbnail_url ? (
                  <img
                    src={candidate.thumbnail_url}
                    alt="Candidate thumbnail"
                    className="h-full w-full object-cover"
                    onError={(e) => {
                      e.target.style.display = "none"
                      e.target.nextSibling.style.display = "flex"
                    }}
                  />
                ) : null}
                <div className={`h-full w-full items-center justify-center text-[10px] text-slate-600 ${candidate.thumbnail_url ? "hidden" : "flex"}`}>
                  Thumbnail unavailable
                </div>
              </div>
            </div>

            <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
              <div className="text-[10px] uppercase tracking-wider text-slate-500">
                Source URL
              </div>
              <a
                href={candidate.source_url}
                target="_blank"
                rel="noreferrer"
                className="mt-1 block break-all text-xs text-cyan-300 hover:text-cyan-200 hover:underline"
              >
                {candidate.source_url}
              </a>
            </div>

            {candidate.page_url && candidate.page_url !== candidate.source_url && (
              <div className="rounded-md border border-slate-800 bg-slate-950 p-3">
                <div className="text-[10px] uppercase tracking-wider text-slate-500">
                  Page URL
                </div>
                <a
                  href={candidate.page_url}
                  target="_blank"
                  rel="noreferrer"
                  className="mt-1 block break-all text-xs text-cyan-300 hover:text-cyan-200 hover:underline"
                >
                  {candidate.page_url}
                </a>
              </div>
            )}
          </section>
        </div>

        {/* Footer actions */}
        <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-800 px-6 py-4">
          <a
            href={candidate.source_url}
            target="_blank"
            rel="noreferrer"
            className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-500"
          >
            Open candidate ↗
          </a>
          <button
            onClick={handleDismiss}
            disabled={busy}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:border-red-500/60 hover:text-red-300 disabled:opacity-50"
          >
            Dismiss as false positive
          </button>
          <a
            href={candidate.source_url}
            target="_blank"
            rel="noreferrer"
            className="rounded-md bg-red-500 px-3 py-1.5 text-xs font-semibold text-slate-50 hover:bg-red-400 disabled:opacity-50"
          >
            Send DMCA notice
          </a>
        </footer>
      </div>
    </div>
  )
}