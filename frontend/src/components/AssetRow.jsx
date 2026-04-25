// src/components/AssetRow.jsx
import { useState } from "react"

import StatusPill from "./StatusPill.jsx"

function formatWhen(iso) {
  if (!iso) return ""
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export default function AssetRow({ asset, liveOverride }) {
  const [expanded, setExpanded] = useState(false)

  const merged = liveOverride ?? asset
  const {
    status,
    fingerprint_status,
    watermark_status,
    download_status,
    source_url,
  } = merged

  const showDownloadPill = download_status && download_status !== "n/a"

  return (
    <article className="rounded-xl border border-slate-800 bg-slate-900/60 transition hover:border-slate-700">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-4 px-4 py-3 text-left"
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="truncate text-sm font-semibold text-slate-100">
              {merged.title}
            </span>
            {source_url && (
              <span className="rounded bg-slate-800 px-1.5 py-0.5 text-[9px] font-semibold uppercase text-slate-400">
                URL
              </span>
            )}
          </div>
          {merged.description && (
            <div className="truncate text-xs text-slate-400">
              {merged.description}
            </div>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {showDownloadPill && <StatusPill label="Download" value={download_status} />}
          <StatusPill label="Fingerprint" value={fingerprint_status} />
          <StatusPill label="Watermark" value={watermark_status} />
          <StatusPill label="Overall" value={status} />
        </div>

        <span className="shrink-0 text-xs text-slate-500">
          {formatWhen(merged.created_at)}
        </span>

        <span className="shrink-0 text-xs text-slate-500">
          {expanded ? "▾" : "▸"}
        </span>
      </button>

      {expanded && (
        <div className="grid grid-cols-2 gap-4 border-t border-slate-800 px-4 py-3 text-xs">
          <div>
            <div className="text-[10px] uppercase tracking-wider text-slate-500">
              Asset ID
            </div>
            <div className="mt-1 font-mono text-slate-300">{merged.id}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-slate-500">
              Video path
            </div>
            <div className="mt-1 font-mono text-slate-300 break-all">
              {merged.video_path || "(pending download)"}
            </div>
          </div>
          {source_url && (
            <div className="col-span-2">
              <div className="text-[10px] uppercase tracking-wider text-slate-500">
                Source URL
              </div>
              <a
                href={source_url}
                target="_blank"
                rel="noreferrer"
                className="mt-1 block truncate text-cyan-300 hover:text-cyan-200 hover:underline"
                title={source_url}
              >
                {source_url}
              </a>
            </div>
          )}
          <div>
            <div className="text-[10px] uppercase tracking-wider text-slate-500">
              Created
            </div>
            <div className="mt-1 text-slate-300">{formatWhen(merged.created_at)}</div>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wider text-slate-500">
              Updated
            </div>
            <div className="mt-1 text-slate-300">{formatWhen(merged.updated_at)}</div>
          </div>
        </div>
      )}
    </article>
  )
}