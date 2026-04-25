// src/components/UploadZone.jsx
import { useRef, useState } from "react"

import { triggerIngest, uploadAsset, uploadAssetFromUrl } from "../api/client.js"

const ACCEPT = "video/*"

/**
 * Props:
 *   onUploaded(asset): called after upload + ingest kickoff succeeds.
 */
export default function UploadZone({ onUploaded }) {
  const [mode, setMode] = useState("file")  // "file" | "url"
  const [dragOver, setDragOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const inputRef = useRef(null)

  // URL-mode state
  const [url, setUrl] = useState("")
  const [urlTitle, setUrlTitle] = useState("")

  const resetUrlForm = () => {
    setUrl("")
    setUrlTitle("")
  }

  // -------- File upload path --------
  const handleFile = async (file) => {
    if (!file) return
    if (!file.type.startsWith("video/")) {
      setError(`Not a video: ${file.type || "unknown"}`)
      return
    }
    const defaultTitle = file.name.replace(/\.[^/.]+$/, "")
    const title = window.prompt("Asset title?", defaultTitle)
    if (!title) return

    setBusy(true)
    setError(null)
    try {
      const asset = await uploadAsset({ file, title, description: "" })
      await triggerIngest(asset.id)
      onUploaded?.(asset)
    } catch (exc) {
      setError(exc.message)
    } finally {
      setBusy(false)
    }
  }

  const onDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files?.[0]
    handleFile(file)
  }

  const onFilePicked = (e) => {
    const file = e.target.files?.[0]
    handleFile(file)
    e.target.value = ""
  }

  // -------- URL ingest path --------
  const submitUrl = async (e) => {
    e?.preventDefault()
    const cleanUrl = url.trim()
    const cleanTitle = urlTitle.trim()
    if (!cleanUrl || !cleanTitle) {
      setError("URL and title are required.")
      return
    }

    setBusy(true)
    setError(null)
    try {
      const asset = await uploadAssetFromUrl({ url: cleanUrl, title: cleanTitle })
      // Download is kicked off on the backend; no separate ingest call needed.
      onUploaded?.(asset)
      resetUrlForm()
    } catch (exc) {
      setError(exc.message)
    } finally {
      setBusy(false)
    }
  }

  const modeBtn = (id, label) => {
    const active = mode === id
    return (
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation()
          setMode(id)
          setError(null)
        }}
        className={`rounded-md px-3 py-1 text-xs font-medium transition ${
          active
            ? "bg-slate-800 text-slate-100"
            : "text-slate-400 hover:text-slate-200"
        }`}
      >
        {label}
      </button>
    )
  }

  return (
    <div className="rounded-xl border-2 border-dashed border-slate-700 bg-slate-900/40 p-5 transition hover:border-slate-500">
      {/* Mode toggle */}
      <div className="mb-4 flex items-center justify-center gap-1 rounded-full border border-slate-800 bg-slate-950 p-1">
        {modeBtn("file", "Upload file")}
        {modeBtn("url",  "Paste URL")}
      </div>

      {mode === "file" ? (
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragOver(true)
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
          className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg px-6 py-8 text-center transition ${
            dragOver ? "bg-cyan-400/5 ring-2 ring-cyan-400" : ""
          } ${busy ? "pointer-events-none opacity-60" : ""}`}
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPT}
            onChange={onFilePicked}
            className="hidden"
          />
          <div className="text-4xl text-slate-600">⬆</div>
          <div className="text-sm font-semibold text-slate-200">
            {busy ? "Uploading..." : "Drop a video here, or click to browse"}
          </div>
          <div className="text-xs text-slate-500">
            Ingest starts automatically after upload.
          </div>
        </div>
      ) : (
        <form onSubmit={submitUrl} className="space-y-3">
          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              Video URL
            </label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://www.youtube.com/watch?v=... or direct MP4 URL"
              disabled={busy}
              className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-slate-500 focus:outline-none disabled:opacity-50"
              required
            />
          </div>
          <div>
            <label className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              Title
            </label>
            <input
              type="text"
              value={urlTitle}
              onChange={(e) => setUrlTitle(e.target.value)}
              placeholder="What is this asset?"
              disabled={busy}
              className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 focus:border-slate-500 focus:outline-none disabled:opacity-50"
              required
              maxLength={255}
            />
          </div>
          <div className="flex items-center justify-between pt-1">
            <span className="text-[10px] text-slate-500">
              Supports YouTube, TikTok, direct MP4 links via yt-dlp.
            </span>
            <button
              type="submit"
              disabled={busy || !url.trim() || !urlTitle.trim()}
              className="rounded-md bg-cyan-500 px-4 py-1.5 text-xs font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:opacity-50"
            >
              {busy ? "Starting..." : "Ingest from URL"}
            </button>
          </div>
        </form>
      )}

      {error && (
        <p className="mt-3 rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
          {error}
        </p>
      )}
    </div>
  )
}