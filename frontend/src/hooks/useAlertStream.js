// src/hooks/useAlertStream.js
import { useCallback, useEffect, useRef, useState } from "react"

import { listAlerts } from "../api/client.js"

const MAX_BACKOFF_MS = 30_000
const INITIAL_BACKOFF_MS = 1_000

/**
 * Build the WebSocket URL from the current page origin.
 * Works in dev (via Vite proxy) and in prod (same-origin deploy).
 */
function wsUrl() {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:"
  return `${scheme}//${window.location.host}/ws/alerts`
}

/**
 * Live alert feed.
 *
 * Returns:
 *   alerts            Array of alerts, newest first.
 *   connectionStatus  "connecting" | "open" | "closed" | "error"
 *   error             null | string -- last fetch/connection error, for UI display.
 *   refresh()         Re-run the history fetch. Handy after bulk actions.
 *   replaceAlert(a)   Swap a single alert in the list by id. Use after PATCH/POST.
 */
export function useAlertStream() {
  const [alerts, setAlerts] = useState([])
  const [connectionStatus, setConnectionStatus] = useState("connecting")
  const [error, setError] = useState(null)

  const socketRef = useRef(null)
  const backoffRef = useRef(INITIAL_BACKOFF_MS)
  const reconnectTimerRef = useRef(null)
  const isActiveRef = useRef(true)

  /** Merge: prepend new, deduplicate by id, keep sorted newest-first. */
  const upsertAlert = useCallback((incoming) => {
    setAlerts((current) => {
      const without = current.filter((a) => a.id !== incoming.id)
      return [incoming, ...without]
    })
  }, [])

  const replaceAlert = useCallback((updated) => {
    setAlerts((current) =>
      current.map((a) => (a.id === updated.id ? updated : a)),
    )
  }, [])

  const refresh = useCallback(async () => {
    try {
      const history = await listAlerts()
      setAlerts(history)
      setError(null)
    } catch (exc) {
      setError(exc.message)
    }
  }, [])

  // Main effect: load history, open socket, reconnect on drop.
  useEffect(() => {
    isActiveRef.current = true

    const connect = () => {
      if (!isActiveRef.current) return

      setConnectionStatus("connecting")
      const socket = new WebSocket(wsUrl())
      socketRef.current = socket

      socket.onopen = () => {
        if (!isActiveRef.current) return
        backoffRef.current = INITIAL_BACKOFF_MS
        setConnectionStatus("open")
        setError(null)
      }

      socket.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data)
          if (msg.type === "alert.created" && msg.alert) {
            upsertAlert(msg.alert)
          }
        } catch (exc) {
          // Malformed server message; log but don't crash the stream.
          console.warn("ws_parse_failed", exc, evt.data)
        }
      }

      socket.onerror = () => {
        if (!isActiveRef.current) return
        setConnectionStatus("error")
      }

      socket.onclose = () => {
        if (!isActiveRef.current) return
        setConnectionStatus("closed")
        const delay = backoffRef.current
        backoffRef.current = Math.min(delay * 2, MAX_BACKOFF_MS)
        reconnectTimerRef.current = window.setTimeout(connect, delay)
      }
    }

    // Kick off: history first, then socket.
    refresh().finally(connect)

    return () => {
      isActiveRef.current = false
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current)
      }
      if (socketRef.current) {
        socketRef.current.close()
      }
    }
  }, [refresh, upsertAlert])

  return { alerts, connectionStatus, error, refresh, replaceAlert }
}