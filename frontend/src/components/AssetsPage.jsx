// src/components/AssetsPage.jsx
import { useCallback, useEffect, useState } from "react"

import { listAssets } from "../api/client.js"
import { useEventStream } from "../hooks/useEventStream.js"
import AssetRow from "./AssetRow.jsx"
import UploadZone from "./UploadZone.jsx"

const STATUS_DOT = {
  open: "bg-emerald-400",
  connecting: "bg-yellow-400 animate-pulse",
  closed: "bg-slate-500",
  error: "bg-red-500",
}

export default function AssetsPage() {
  const { assetEvents, connectionStatus } = useEventStream()

  const [assets, setAssets] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const list = await listAssets()
      setAssets(list)
    } catch (exc) {
      setError(exc.message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const handleUploaded = useCallback(
    async (asset) => {
      // Prepend the new asset to the top so it's immediately visible.
      setAssets((current) => [asset, ...current])
      // Refresh shortly after to pick up any server-side fields we don't know about.
      setTimeout(refresh, 1500)
    },
    [refresh],
  )

  return (
    <section className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-100">Assets</h1>

        <div className="flex items-center gap-2 rounded-full border border-slate-800 bg-slate-900 px-3 py-1 text-xs">
          <span className={`h-2 w-2 rounded-full ${STATUS_DOT[connectionStatus] ?? STATUS_DOT.closed}`} />
          <span className="capitalize text-slate-300">{connectionStatus}</span>
        </div>

        <span className="text-xs text-slate-500">{assets.length} registered</span>

        <button
          onClick={refresh}
          className="ml-auto rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-200 hover:border-slate-500"
        >
          Refresh
        </button>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto p-6">
        <UploadZone onUploaded={handleUploaded} />

        {error && (
          <p className="rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}

        {loading ? (
          <div className="py-8 text-center text-sm text-slate-500">Loading...</div>
        ) : assets.length === 0 ? (
          <div className="rounded-xl border border-dashed border-slate-800 p-10 text-center text-sm text-slate-500">
            No assets yet. Drop a video above to register your first one.
          </div>
        ) : (
          <div className="space-y-2">
            {assets.map((asset) => (
              <AssetRow
                key={asset.id}
                asset={asset}
                liveOverride={assetEvents.get(asset.id)}
              />
            ))}
          </div>
        )}
      </div>
    </section>
  )
}