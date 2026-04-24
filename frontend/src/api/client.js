// src/api/client.js
// Thin wrapper around fetch for the alerts + assets API.
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
  if (res.status === 204) return null
  return res.json()
}

// ---------------------------------------------------------------------------
// Alerts
// ---------------------------------------------------------------------------

export function listAlerts({ skip = 0, limit = 50, status, severity } = {}) {
  const params = new URLSearchParams({ skip, limit })
  if (status) params.set("status", status)
  if (severity) params.set("severity", severity)
  return request(`/alerts?${params}`)
}

export function updateAlertStatus(alertId, newStatus) {
  return request(`/alerts/${alertId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status: newStatus }),
  })
}

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

export function simulateAlert() {
  return request(`/alerts/_simulate`, { method: "POST" })
}

// ---------------------------------------------------------------------------
// Assets
// ---------------------------------------------------------------------------

export function listAssets({ skip = 0, limit = 50 } = {}) {
  const params = new URLSearchParams({ skip, limit })
  return request(`/assets?${params}`)
}

export function getAsset(assetId) {
  return request(`/assets/${assetId}`)
}

export async function uploadAsset({ file, title, description }) {
  const form = new FormData()
  form.append("file", file)
  form.append("title", title)
  if (description) form.append("description", description)

  const res = await fetch("/api/assets", {
    method: "POST",
    body: form,
    // Do NOT set Content-Type -- browser sets it with multipart boundary.
  })
  if (!res.ok) {
    const text = await res.text().catch(() => "")
    throw new Error(`${res.status} ${res.statusText}: ${text || "upload failed"}`)
  }
  return res.json()
}

export function triggerIngest(assetId) {
  return request(`/assets/${assetId}/ingest`, { method: "POST" })
}