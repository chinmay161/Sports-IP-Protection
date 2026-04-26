// src/components/LookalikePage.jsx
import { useCallback, useEffect, useMemo, useState } from "react"

import {
  listAssets,
  listVisualCandidates,
  triggerVisualDiscovery,
} from "../api/client.js"
import LookalikeCandidate from "./LookalikeCandidate.jsx"
import LookalikeComparison from "./LookalikeComparison.jsx"

const PLATFORMS = ["all", "youtube", "tiktok", "telegram", "web"]

export default function LookalikePage() {
  const [assets, setAssets] = useState([])
  const [assetsLoading, setAssetsLoading] = useState(true)
  const [selectedAssetId, setSelectedAssetId] = useState(null)

  const [candidates, setCandidates] = useState([])
  const [candidatesLoading, setCandidatesLoading] = useState(false)
  const [error, setError] = useState(null)

  const [discovering, setDiscovering] = useState(false)
  const [discoverMessage, setDiscoverMessage] = useState(null)

  const [platformFilter, setPlatformFilter] = useState("all")

  const [comparing, setComparing] = useState(null)

  useEffect(() => {
    let cancelled = false
    listAssets({ limit: 50 })
      .then((res) => {
        if (cancelled) return
        const ready = (res.items ?? res ?? []).filter((a) => a.fingerprint_status === "ready")
        setAssets(ready)
        if (ready.length > 0) setSelectedAssetId(ready[0].id)
      })
      .catch((exc) => !cancelled && setError(exc.message))
      .finally(() => !cancelled && setAssetsLoading(false))
    return () => { cancelled = true }
  }, [])

  const fetchCandidates = useCallback(async (assetId) => {
    if (!assetId) return
    setCandidatesLoading(true)
    setError(null)
    try {
      const res = await listVisualCandidates(assetId)
      setCandidates(res.items ?? [])
    } catch (exc) {
      setError(exc.message)
    } finally {
      setCandidatesLoading(false)
    }
  }, [])

  useEffect(() => {
    if (selectedAssetId) fetchCandidates(selectedAssetId)
  }, [selectedAssetId, fetchCandidates])

  const handleDiscover = async () => {
    if (!selectedAssetId) return
    setDiscovering(true)
    setDiscoverMessage(null)
    try {
      const res = await triggerVisualDiscovery(selectedAssetId, { query: "sports highlights" })
      setDiscoverMessage({
        kind: "success",
        text: `Discovery queued (task ${res.task_id?.slice(0, 8)}...). Refresh in 30 seconds.`,
      })
    } catch (exc) {
      setDiscoverMessage({ kind: "error", text: exc.message })
    } finally {
      setDiscovering(false)
      setTimeout(() => setDiscoverMessage(null), 8000)
    }
  }

  const handleDismissed = (candidateId) => {
    setCandidates((prev) => prev.filter((c) => c.id !== candidateId))
  }

  const filtered = useMemo(() => {
    if (platformFilter === "all") return candidates
    return candidates.filter((c) => c.platform === platformFilter)
  }, [candidates, platformFilter])

  const stats = useMemo(() => {
    const out = { total: candidates.length, high: 0, medium: 0, low: 0 }
    candidates.forEach((c) => {
      if (c.visual_score >= 0.8) out.high++
      else if (c.visual_score >= 0.5) out.medium++
      else out.low++
    })
    return out
  }, [candidates])

  const selectedAsset = assets.find((a) => a.id === selectedAssetId)

  return (
    <section className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-100">Lookalike</h1>

        <div className="flex items-center gap-3 text-xs">
          {stats.high > 0 && <span className="text-red-300">{stats.high} strong</span>}
          {stats.medium > 0 && <span className="text-orange-300">{stats.medium} medium</span>}
          {stats.low > 0 && <span className="text-slate-400">{stats.low} weak</span>}
          <span className="text-slate-500">·</span>
          <span className="text-slate-400">{stats.total} total</span>
        </div>

        <div className="ml-auto flex items-center gap-2">
          {assets.length > 0 && (
            <select
              value={selectedAssetId ?? ""}
              onChange={(e) => setSelectedAssetId(e.target.value)}
              className="rounded-md border border-slate-700 bg-slate-900 px-3 py-1.5 text-xs text-slate-200"
            >
              {assets.map((a) => (
                <option key={a.id} value={a.id}>{a.title}</option>
              ))}
            </select>
          )}

          <select
            value={platformFilter}
            onChange={(e) => setPlatformFilter(e.target.value)}
            className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
          >
            {PLATFORMS.map((p) => (
              <option key={p} value={p}>{p === "all" ? "All platforms" : p}</option>
            ))}
          </select>

          <button
            onClick={() => fetchCandidates(selectedAssetId)}
            className="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-200 hover:border-slate-500"
          >
            Refresh
          </button>

          <button
            onClick={handleDiscover}
            disabled={discovering || !selectedAssetId}
            className="rounded-md bg-cyan-500 px-3 py-1 text-xs font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:opacity-50"
          >
            {discovering ? "Discovering..." : "Discover lookalikes"}
          </button>
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-6">
        {discoverMessage && (
          <div className={`mb-4 rounded border px-3 py-2 text-xs ${
            discoverMessage.kind === "success"
              ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
              : "border-red-500/40 bg-red-500/10 text-red-300"
          }`}>
            {discoverMessage.text}
          </div>
        )}

        {error && (
          <p className="mb-4 rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}

        {selectedAsset && (
          <div className="mb-4 text-xs text-slate-400">
            Showing visual lookalikes for: <span className="font-semibold text-slate-200">{selectedAsset.title}</span>
          </div>
        )}

        {assetsLoading || candidatesLoading ? (
          <div className="py-8 text-center text-sm text-slate-500">Loading...</div>
        ) : assets.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-800 p-12 text-center">
            <div className="text-sm text-slate-400">No ready assets to scan.</div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-800 p-12 text-center">
            <div className="text-sm text-slate-400">
              {candidates.length === 0
                ? "No lookalikes found yet for this asset."
                : "No candidates match the current filter."}
            </div>
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {filtered.map((c) => (
              <LookalikeCandidate
                key={c.id}
                candidate={c}
                onDismissed={handleDismissed}
                onCompare={(cand) => setComparing({ candidate: cand })}
              />
            ))}
          </div>
        )}
      </div>

      {comparing && (
        <LookalikeComparison
          asset={selectedAsset}
          candidate={comparing.candidate}
          onClose={() => setComparing(null)}
          onDismissed={handleDismissed}
        />
      )}
    </section>
  )
}
