// src/components/UploadZone.jsx
import { useRef, useState } from "react"

import { triggerIngest, uploadAsset } from "../api/client.js"

const ACCEPT = "video/*"

/**
 * Drag-and-drop + click-to-browse file picker.
 * On drop: prompts for title, uploads, auto-triggers ingest.
 *
 * Props:
 *   onUploaded(asset): called after upload + ingest kickoff succeeds.
 */
export default function UploadZone({ onUploaded }) {
  const [dragOver, setDragOver] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const inputRef = useRef(null)

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
    e.target.value = "" // allow re-selecting the same file
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={onDrop}
      onClick={() => inputRef.current?.click()}
      className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border-2 border-dashed px-6 py-10 text-center transition ${
        dragOver
          ? "border-cyan-400 bg-cyan-400/5"
          : "border-slate-700 bg-slate-900/40 hover:border-slate-500"
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

      <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-600">
        <span>Or</span>
        <button
          disabled
          onClick={(e) => e.stopPropagation()}
          className="cursor-not-allowed rounded-md border border-slate-800 px-2 py-0.5 text-slate-600"
          title="Requires the crawler module (Dev 1 working on it)"
        >
          Paste URL (coming soon)
        </button>
      </div>

      {error && (
        <p className="mt-2 rounded border border-red-500/40 bg-red-500/10 px-3 py-1 text-xs text-red-300">
          {error}
        </p>
      )}
    </div>
  )
}