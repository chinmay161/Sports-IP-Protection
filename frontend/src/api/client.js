// src/api/client.js
// Thin wrapper around fetch for the alerts API.
// All requests go through Vite's /api proxy -> FastAPI at 127.0.0.1:8001.

const BASE = "/api"

/** Internal helper: fetch + JSON parse + error on non-2xx. */
async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => "")
    throw new Error(`${res.status} ${res.statusText}: ${text || path}`)
  }
  // 204 No Content has an empty body -- guard against it.
  if (res.status === 204) return null
  return res.json()
}

/** GET /alerts -- returns an array of alert objects, newest first. */
export function listAlerts({ skip = 0, limit = 50, status, severity } = {}) {
  const params = new URLSearchParams({ skip, limit })
  if (status) params.set("status", status)
  if (severity) params.set("severity", severity)
  return request(`/alerts?${params}`)
}

/**
 * PATCH /alerts/{id}/status
 * Valid values: open | acknowledged | dmca_initiated | resolved
 */
export function updateAlertStatus(alertId, newStatus) {
  return request(`/alerts/${alertId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status: newStatus }),
  })
}

/**
 * POST /alerts/{id}/dmca
 * Generates the DMCA notice text and marks the alert as dmca_initiated.
 */
export function initiateDmca(alertId, { assetTitle, assetOwner, infringingUrl, contactEmail }) {
  return request(`/alerts/${alertId}/dmca`, {
    method: "POST",
    body: JSON.stringify({
      asset_title: assetTitle,
      asset_owner: assetOwner,
      infringing_url: infringingUrl,
      contact_email: contactEmail,
    }),
  })
}

/** POST /alerts/_simulate -- dev only, requires AUTH_DISABLED=true on the backend. */
export function simulateAlert() {
  return request(`/alerts/_simulate`, { method: "POST" })
}