import { useCallback, useEffect, useMemo, useState } from "react"

import {
  addLiveStreamSuspectUrls,
  endLiveStream,
  listAssets,
  listLiveStreamViolations,
  listLiveStreams,
  registerLiveStream,
  watermarkLiveSegment,
} from "../api/client.js"

const STATUS_OPTIONS = ["all", "active", "ended", "suspended"]
const VIOLATION_OPTIONS = ["all", "new", "dmca_sent", "resolved"]

const STATUS_STYLE = {
  active: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  ended: "border-slate-600 bg-slate-800/70 text-slate-300",
  suspended: "border-red-500/30 bg-red-500/10 text-red-200",
  new: "border-yellow-500/30 bg-yellow-500/10 text-yellow-200",
  dmca_sent: "border-blue-500/30 bg-blue-500/10 text-blue-200",
  resolved: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
}

function wsUrl() {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:"
  return `${scheme}//${window.location.host}/live-streams/ws`
}

function shortId(value) {
  return value ? `${value.slice(0, 8)}...${value.slice(-4)}` : "-"
}

function fmtDate(value) {
  if (!value) return "-"
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value))
}

function Badge({ value }) {
  return (
    <span className={`rounded-md border px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLE[value] ?? "border-slate-700 bg-slate-900 text-slate-300"}`}>
      {value?.replace("_", " ") ?? "-"}
    </span>
  )
}

function Field({ label, children }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-slate-400">{label}</span>
      {children}
    </label>
  )
}

const inputClass = "w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 outline-none focus:border-sky-500"

export default function LiveStreamsPage() {
  const [streams, setStreams] = useState([])
  const [assets, setAssets] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [violations, setViolations] = useState({ total: 0, items: [] })
  const [streamFilter, setStreamFilter] = useState("all")
  const [violationFilter, setViolationFilter] = useState("all")
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)
  const [connectionStatus, setConnectionStatus] = useState("connecting")
  const [events, setEvents] = useState([])

  const [registerForm, setRegisterForm] = useState({
    assetId: "",
    streamKey: "",
    hlsManifestUrl: "",
    s3Prefix: "",
  })
  const [suspectText, setSuspectText] = useState("")
  const [watermarkForm, setWatermarkForm] = useState({ segmentName: "", payload: "42" })

  const selectedStream = useMemo(
    () => streams.find((stream) => stream.id === selectedId) ?? streams[0] ?? null,
    [streams, selectedId],
  )

  const activeCount = useMemo(
    () => streams.filter((stream) => stream.status === "active").length,
    [streams],
  )

  const refreshStreams = useCallback(async () => {
    try {
      const data = await listLiveStreams({ status: streamFilter })
      setStreams(data)
      setSelectedId((current) => {
        if (current && data.some((stream) => stream.id === current)) return current
        return data[0]?.id ?? null
      })
      setError(null)
    } catch (exc) {
      setError(exc.message)
    } finally {
      setLoading(false)
    }
  }, [streamFilter])

  const refreshViolations = useCallback(async () => {
    if (!selectedStream) {
      setViolations({ total: 0, items: [] })
      return
    }
    try {
      const data = await listLiveStreamViolations(selectedStream.id, {
        status: violationFilter,
        limit: 50,
      })
      setViolations(data)
    } catch (exc) {
      setError(exc.message)
    }
  }, [selectedStream, violationFilter])

  useEffect(() => {
    async function loadAssets() {
      try {
        const data = await listAssets({ limit: 100 })
        setAssets(data)
        setRegisterForm((current) => ({ ...current, assetId: current.assetId || data[0]?.id || "" }))
      } catch (exc) {
        setError(exc.message)
      }
    }
    loadAssets()
  }, [])

  useEffect(() => {
    const id = window.setTimeout(() => {
      setLoading(true)
      refreshStreams()
    }, 0)
    return () => window.clearTimeout(id)
  }, [refreshStreams])

  useEffect(() => {
    const id = window.setTimeout(refreshViolations, 0)
    return () => window.clearTimeout(id)
  }, [refreshViolations])

  useEffect(() => {
    let socket
    let retry
    let closed = false

    function connect() {
      setConnectionStatus("connecting")
      socket = new WebSocket(wsUrl())
      socket.onopen = () => setConnectionStatus("open")
      socket.onmessage = (evt) => {
        try {
          const payload = JSON.parse(evt.data)
          if (payload.type === "ping") return
          setEvents((current) => [{ ...payload, received_at: new Date().toISOString() }, ...current].slice(0, 12))
          refreshStreams()
        } catch {
          setEvents((current) => [{ message: evt.data, received_at: new Date().toISOString() }, ...current].slice(0, 12))
        }
      }
      socket.onerror = () => setConnectionStatus("error")
      socket.onclose = () => {
        if (closed) return
        setConnectionStatus("closed")
        retry = window.setTimeout(connect, 2500)
      }
    }

    connect()
    return () => {
      closed = true
      window.clearTimeout(retry)
      socket?.close()
    }
  }, [refreshStreams])

  const handleRegister = async (evt) => {
    evt.preventDefault()
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      const stream = await registerLiveStream(registerForm)
      setNotice(`Registered ${stream.stream_key}`)
      setSelectedId(stream.id)
      setRegisterForm((current) => ({
        ...current,
        streamKey: "",
        hlsManifestUrl: "",
        s3Prefix: "",
      }))
      await refreshStreams()
    } catch (exc) {
      setError(exc.message)
    } finally {
      setBusy(false)
    }
  }

  const handleEnd = async (streamId) => {
    setBusy(true)
    setError(null)
    try {
      await endLiveStream(streamId)
      setNotice("Stream ended")
      await refreshStreams()
    } catch (exc) {
      setError(exc.message)
    } finally {
      setBusy(false)
    }
  }

  const handleAddSuspects = async (evt) => {
    evt.preventDefault()
    if (!selectedStream) return
    const urls = suspectText
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
    if (urls.length === 0) return
    setBusy(true)
    setError(null)
    try {
      const res = await addLiveStreamSuspectUrls(selectedStream.id, urls)
      setNotice(`${res.suspect_url_count} suspect URLs monitored`)
      setSuspectText("")
    } catch (exc) {
      setError(exc.message)
    } finally {
      setBusy(false)
    }
  }

  const handleWatermark = async (evt) => {
    evt.preventDefault()
    if (!selectedStream) return
    setBusy(true)
    setError(null)
    try {
      const row = await watermarkLiveSegment(selectedStream.id, watermarkForm)
      setNotice(`Watermarked ${row.segment_name}`)
      setWatermarkForm((current) => ({ ...current, segmentName: "" }))
    } catch (exc) {
      setError(exc.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="flex h-full flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-100">Live Streams</h1>
        <span className="rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-200">
          {activeCount} active
        </span>
        <span className="rounded-md border border-slate-700 px-2 py-1 text-xs text-slate-300">
          WS {connectionStatus}
        </span>
        <select
          value={streamFilter}
          onChange={(evt) => setStreamFilter(evt.target.value)}
          className="ml-auto rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-slate-200"
        >
          {STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>{status === "all" ? "All streams" : status}</option>
          ))}
        </select>
        <button
          onClick={refreshStreams}
          className="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-200 hover:border-slate-500"
        >
          Refresh
        </button>
      </header>

      <div className="flex-1 overflow-y-auto p-6">
        {(error || notice) && (
          <div className="mb-4 grid gap-2">
            {error && <div className="rounded-md border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">{error}</div>}
            {notice && <div className="rounded-md border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-200">{notice}</div>}
          </div>
        )}

        <div className="grid gap-4 xl:grid-cols-[minmax(320px,420px)_1fr]">
          <div className="space-y-4">
            <form onSubmit={handleRegister} className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold text-slate-100">Register stream</h2>
                <span className="text-[11px] text-slate-500">{assets.length} assets</span>
              </div>
              <div className="grid gap-3">
                <Field label="Asset">
                  <select
                    value={registerForm.assetId}
                    onChange={(evt) => setRegisterForm((current) => ({ ...current, assetId: evt.target.value }))}
                    className={inputClass}
                    required
                  >
                    {assets.length === 0 && <option value="">No assets loaded</option>}
                    {assets.map((asset) => (
                      <option key={asset.id} value={asset.id}>
                        {asset.title || shortId(asset.id)}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Stream key">
                  <input
                    value={registerForm.streamKey}
                    onChange={(evt) => setRegisterForm((current) => ({ ...current, streamKey: evt.target.value }))}
                    className={inputClass}
                    placeholder="match-ucl-2026-04"
                    required
                  />
                </Field>
                <Field label="HLS manifest URL">
                  <input
                    value={registerForm.hlsManifestUrl}
                    onChange={(evt) => setRegisterForm((current) => ({ ...current, hlsManifestUrl: evt.target.value }))}
                    className={inputClass}
                    placeholder="https://cdn.example.com/live/index.m3u8"
                    required
                  />
                </Field>
                <Field label="S3 segment prefix">
                  <input
                    value={registerForm.s3Prefix}
                    onChange={(evt) => setRegisterForm((current) => ({ ...current, s3Prefix: evt.target.value }))}
                    className={inputClass}
                    placeholder="streams/{stream_id}/segments/"
                    required
                  />
                </Field>
                <button
                  disabled={busy || !registerForm.assetId}
                  className="rounded-md bg-sky-500 px-3 py-2 text-sm font-medium text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  Register
                </button>
              </div>
            </form>

            <div className="rounded-lg border border-slate-800 bg-slate-900/50">
              <div className="border-b border-slate-800 px-4 py-3">
                <h2 className="text-sm font-semibold text-slate-100">Streams</h2>
              </div>
              <div className="max-h-[460px] overflow-y-auto">
                {loading ? (
                  <div className="p-6 text-center text-sm text-slate-500">Loading streams...</div>
                ) : streams.length === 0 ? (
                  <div className="p-6 text-center text-sm text-slate-500">No live streams registered.</div>
                ) : (
                  streams.map((stream) => {
                    const selected = selectedStream?.id === stream.id
                    return (
                      <button
                        key={stream.id}
                        onClick={() => setSelectedId(stream.id)}
                        className={`w-full border-b border-slate-800 px-4 py-3 text-left transition last:border-b-0 ${selected ? "bg-slate-800/70" : "hover:bg-slate-800/40"}`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <div className="truncate text-sm font-medium text-slate-100">{stream.stream_key}</div>
                            <div className="mt-1 text-xs text-slate-500">{shortId(stream.id)}</div>
                          </div>
                          <Badge value={stream.status} />
                        </div>
                        <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
                          <span>{stream.violation_count} violations</span>
                          <span>{fmtDate(stream.started_at)}</span>
                        </div>
                      </button>
                    )
                  })
                )}
              </div>
            </div>
          </div>

          <div className="space-y-4">
            {selectedStream ? (
              <>
                <div className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                  <div className="flex flex-wrap items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <h2 className="truncate text-base font-semibold text-slate-100">{selectedStream.stream_key}</h2>
                        <Badge value={selectedStream.status} />
                      </div>
                      <div className="mt-2 grid gap-1 text-xs text-slate-400">
                        <div className="truncate">Manifest: {selectedStream.hls_manifest_url}</div>
                        <div className="truncate">S3: {selectedStream.s3_prefix}</div>
                        <div>Asset: {shortId(selectedStream.asset_id)}</div>
                      </div>
                    </div>
                    <button
                      onClick={() => handleEnd(selectedStream.id)}
                      disabled={busy || selectedStream.status !== "active"}
                      className="rounded-md border border-red-500/40 px-3 py-2 text-xs font-medium text-red-200 hover:bg-red-500/10 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      End stream
                    </button>
                  </div>
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                  <form onSubmit={handleAddSuspects} className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                    <h2 className="mb-3 text-sm font-semibold text-slate-100">Suspect URLs</h2>
                    <textarea
                      value={suspectText}
                      onChange={(evt) => setSuspectText(evt.target.value)}
                      className={`${inputClass} min-h-28 resize-y`}
                      placeholder="https://piracy.example/live/feed.m3u8"
                    />
                    <button
                      disabled={busy || !suspectText.trim()}
                      className="mt-3 rounded-md bg-slate-100 px-3 py-2 text-sm font-medium text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Add URLs
                    </button>
                  </form>

                  <form onSubmit={handleWatermark} className="rounded-lg border border-slate-800 bg-slate-900/50 p-4">
                    <h2 className="mb-3 text-sm font-semibold text-slate-100">Watermark segment</h2>
                    <div className="grid gap-3 sm:grid-cols-[1fr_140px]">
                      <Field label="Segment name">
                        <input
                          value={watermarkForm.segmentName}
                          onChange={(evt) => setWatermarkForm((current) => ({ ...current, segmentName: evt.target.value }))}
                          className={inputClass}
                          placeholder="seg_00142.ts"
                          required
                        />
                      </Field>
                      <Field label="Payload">
                        <input
                          type="number"
                          min="0"
                          max="4294967295"
                          value={watermarkForm.payload}
                          onChange={(evt) => setWatermarkForm((current) => ({ ...current, payload: evt.target.value }))}
                          className={inputClass}
                          required
                        />
                      </Field>
                    </div>
                    <button
                      disabled={busy || !watermarkForm.segmentName.trim()}
                      className="mt-3 rounded-md bg-sky-500 px-3 py-2 text-sm font-medium text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      Trigger watermark
                    </button>
                  </form>
                </div>

                <div className="rounded-lg border border-slate-800 bg-slate-900/50">
                  <div className="flex flex-wrap items-center gap-3 border-b border-slate-800 px-4 py-3">
                    <h2 className="text-sm font-semibold text-slate-100">Violations</h2>
                    <span className="text-xs text-slate-500">{violations.total} total</span>
                    <select
                      value={violationFilter}
                      onChange={(evt) => setViolationFilter(evt.target.value)}
                      className="ml-auto rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-slate-200"
                    >
                      {VIOLATION_OPTIONS.map((status) => (
                        <option key={status} value={status}>{status === "all" ? "All statuses" : status}</option>
                      ))}
                    </select>
                    <button
                      onClick={refreshViolations}
                      className="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-200 hover:border-slate-500"
                    >
                      Refresh
                    </button>
                  </div>
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[760px] text-left text-sm">
                      <thead className="text-xs text-slate-500">
                        <tr className="border-b border-slate-800">
                          <th className="px-4 py-3 font-medium">Source</th>
                          <th className="px-4 py-3 font-medium">Match</th>
                          <th className="px-4 py-3 font-medium">Confidence</th>
                          <th className="px-4 py-3 font-medium">Severity</th>
                          <th className="px-4 py-3 font-medium">DMCA</th>
                          <th className="px-4 py-3 font-medium">Detected</th>
                        </tr>
                      </thead>
                      <tbody>
                        {violations.items.length === 0 ? (
                          <tr>
                            <td colSpan="6" className="px-4 py-8 text-center text-sm text-slate-500">
                              No live violations for this stream.
                            </td>
                          </tr>
                        ) : (
                          violations.items.map((violation) => (
                            <tr key={violation.id} className="border-b border-slate-800 last:border-b-0">
                              <td className="max-w-[260px] truncate px-4 py-3 text-slate-300">{violation.source_url}</td>
                              <td className="px-4 py-3 text-slate-300">{violation.match_type}</td>
                              <td className="px-4 py-3 text-slate-300">{Math.round(violation.confidence * 100)}%</td>
                              <td className="px-4 py-3"><Badge value={violation.severity} /></td>
                              <td className="px-4 py-3"><Badge value={violation.status} /></td>
                              <td className="px-4 py-3 text-slate-400">{fmtDate(violation.detected_at)}</td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </>
            ) : (
              <div className="rounded-lg border border-dashed border-slate-800 p-12 text-center text-sm text-slate-500">
                Select or register a live stream to manage monitoring.
              </div>
            )}

            <div className="rounded-lg border border-slate-800 bg-slate-900/50">
              <div className="border-b border-slate-800 px-4 py-3">
                <h2 className="text-sm font-semibold text-slate-100">Realtime stream events</h2>
              </div>
              <div className="max-h-52 overflow-y-auto">
                {events.length === 0 ? (
                  <div className="px-4 py-6 text-sm text-slate-500">Listening for stream.registered and stream.ended.</div>
                ) : (
                  events.map((event, index) => (
                    <div key={`${event.received_at}-${index}`} className="border-b border-slate-800 px-4 py-3 text-xs last:border-b-0">
                      <div className="font-medium text-slate-200">{event.stream_key || event.stream_id || event.message}</div>
                      <div className="mt-1 text-slate-500">
                        {shortId(event.stream_id)} {event.asset_id ? `asset ${shortId(event.asset_id)}` : ""} {fmtDate(event.received_at)}
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
