// src/components/DmcaDraftModal.jsx
//
// Modal that:
//   1) Calls the backend draft endpoint (Gemini → fallback)
//   2) Shows the draft in an editable textarea so operators can review
//   3) Lets them regenerate or send
//
// Sending currently routes through whichever onSend callback the parent
// provides — for alerts that's initiateDmca(), for detections it's the
// existing /dmca endpoint. The AI-drafted text is *not* persisted by the
// draft call itself; it's a transient document until the operator sends.

import { useEffect, useRef, useState } from "react"

export default function DmcaDraftModal({
  open,
  onClose,
  fetchDraft,         // () => Promise<{ notice, provider, model }>
  onSend,             // (editedNotice) => Promise<void>
  contextLabel,       // e.g. "YouTube · ArenaClips · 92% confidence"
}) {
  const [draft, setDraft] = useState("")
  const [provider, setProvider] = useState(null)
  const [model, setModel] = useState(null)

  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [sending, setSending] = useState(false)
  const [sentMessage, setSentMessage] = useState(null)

  const textareaRef = useRef(null)

  // Fetch draft whenever the modal opens. Re-fetch on regenerate.
  const fetchAndSetDraft = async () => {
    setLoading(true)
    setError(null)
    try {
      const result = await fetchDraft()
      setDraft(result.notice ?? "")
      setProvider(result.provider ?? null)
      setModel(result.model ?? null)
    } catch (exc) {
      setError(exc.status === 429
        ? "Gemini rate limit reached. Wait a moment and try again."
        : (exc.message ?? "Failed to draft notice"))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (!open) return
    setDraft("")
    setProvider(null)
    setModel(null)
    setError(null)
    setSentMessage(null)
    fetchAndSetDraft()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  // ESC closes
  useEffect(() => {
    if (!open) return
    const handler = (e) => e.key === "Escape" && !sending && onClose()
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [open, sending, onClose])

  const handleSend = async () => {
    setSending(true)
    setError(null)
    try {
      await onSend?.(draft)
      setSentMessage("DMCA notice sent. Closing in a moment...")
      setTimeout(() => onClose(), 1500)
    } catch (exc) {
      setError(exc.message ?? "Failed to send notice")
      setSending(false)
    }
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(draft)
    } catch {
      // best-effort — fall back to selecting the text
      textareaRef.current?.select()
    }
  }

  if (!open) return null

  const providerBadge =
    provider === "gemini" ? (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-cyan-500/15 border border-cyan-500/40 px-2 py-0.5 text-[10px] font-semibold text-cyan-300">
        <span className="h-1.5 w-1.5 rounded-full bg-cyan-400" />
        Drafted by Gemini ({model})
      </span>
    ) : provider === "fallback" ? (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-yellow-500/15 border border-yellow-500/40 px-2 py-0.5 text-[10px] font-semibold text-yellow-300">
        <span className="h-1.5 w-1.5 rounded-full bg-yellow-400" />
        Template fallback (Gemini unavailable)
      </span>
    ) : null

  return (
    <div
      onClick={() => !sending && onClose()}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur"
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex max-h-[90vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl border border-slate-800 bg-slate-900 shadow-2xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-slate-800 px-6 py-4">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-slate-100">Send DMCA notice</h2>
            <p className="mt-0.5 text-xs text-slate-500 truncate" title={contextLabel}>
              {contextLabel ?? "Review and edit the AI draft before sending."}
            </p>
            <div className="mt-2">{providerBadge}</div>
          </div>
          <button
            onClick={() => !sending && onClose()}
            disabled={sending}
            className="rounded-md border border-slate-700 px-3 py-1 text-xs text-slate-300 hover:border-slate-500 disabled:opacity-40"
          >
            Close
          </button>
        </header>

        <div className="flex flex-1 flex-col overflow-hidden p-5">
          {error && (
            <p className="mb-3 rounded border border-red-500/40 bg-red-500/10 px-3 py-2 text-xs text-red-300">
              {error}
            </p>
          )}

          {sentMessage && (
            <p className="mb-3 rounded border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-xs text-emerald-300">
              {sentMessage}
            </p>
          )}

          {loading ? (
            <div className="flex flex-1 items-center justify-center text-sm text-slate-500">
              Drafting notice with Gemini...
            </div>
          ) : (
            <>
              <label className="text-[10px] uppercase tracking-wider text-slate-500">
                Notice (editable)
              </label>
              <textarea
                ref={textareaRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                disabled={sending}
                spellCheck={false}
                className="mt-1 flex-1 resize-none rounded-md border border-slate-700 bg-slate-950 p-3 font-mono text-xs text-slate-200 focus:border-slate-500 focus:outline-none disabled:opacity-60"
              />
              <p className="mt-2 text-[10px] text-slate-500">
                Replace [Rights Holder Name] and [Contact Email] before sending.
                The AI draft is a starting point — operator review is required.
              </p>
            </>
          )}
        </div>

        <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-slate-800 px-6 py-4">
          <button
            onClick={fetchAndSetDraft}
            disabled={loading || sending}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:border-slate-500 disabled:opacity-40"
          >
            Regenerate
          </button>
          <button
            onClick={handleCopy}
            disabled={loading || sending || !draft}
            className="rounded-md border border-slate-700 px-3 py-1.5 text-xs text-slate-300 hover:border-slate-500 disabled:opacity-40"
          >
            Copy to clipboard
          </button>
          <button
            onClick={handleSend}
            disabled={loading || sending || !draft.trim()}
            className="rounded-md bg-red-500 px-4 py-1.5 text-xs font-semibold text-slate-50 hover:bg-red-400 disabled:opacity-40"
          >
            {sending ? "Sending..." : "Send DMCA notice"}
          </button>
        </footer>
      </div>
    </div>
  )
}