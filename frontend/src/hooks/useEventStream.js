// src/hooks/useEventStream.js
import { useCallback, useEffect, useRef, useState } from "react"

import { listAlerts } from "../api/client.js"

const MAX_BACKOFF_MS = 30_000
const INITIAL_BACKOFF_MS = 1_000

function wsUrl() {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:"
  return `${scheme}//${window.location.host}/ws/events`
}

/**
 * Unified real-time event stream.
 *
 * Handles these server messages:
 *   { type: "alert.created", alert: {...} }
 *   { type: "asset.status_changed", asset: {...} }
 *
 * Returns:
 *   alerts              Array<Alert>, newest first
 *   assetEvents         Map<assetId, Asset>  last-seen status per asset
 *   connectionStatus    "connecting" | "open" | "closed" | "error"
 *   error               null | string
 *   refresh()           Re-fetch alert history from REST
 *   replaceAlert(a)     Swap a single alert in state by id (after PATCH/POST)
 */
export function useEventStream() {
  const [alerts, setAlerts] = useState([])
  const [assetEvents, setAssetEvents] = useState(new Map())
  const [connectionStatus, setConnectionStatus] = useState("connecting")
  const [error, setError] = useState(null)

  const socketRef = useRef(null)
  const backoffRef = useRef(INITIAL_BACKOFF_MS)
  const reconnectTimerRef = useRef(null)
  const isActiveRef = useRef(true)

  const upsertAlert = useCallback((incoming) => {
    setAlerts((current) => {
      const without = current.filter((a) => a.id !== incoming.id)
      return [incoming, ...without]
    })
  }, [])

  const upsertAsset = useCallback((asset) => {
    setAssetEvents((current) => {
      const next = new Map(current)
      next.set(asset.id, asset)
      return next
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
          switch (msg.type) {
            case "alert.created":
              if (msg.alert) upsertAlert(msg.alert)
              break
            case "asset.status_changed":
              if (msg.asset) upsertAsset(msg.asset)
              break
            default:
              console.warn("unknown_event_type", msg.type, msg)
          }
        } catch (exc) {
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

    refresh().finally(connect)

    return () => {
      isActiveRef.current = false
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
      if (socketRef.current) socketRef.current.close()
    }
  }, [refresh, upsertAlert, upsertAsset])

  return {
    alerts,
    assetEvents,
    connectionStatus,
    error,
    refresh,
    replaceAlert,
  }
}