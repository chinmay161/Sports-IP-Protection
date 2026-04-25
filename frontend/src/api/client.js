// src/api/client.js
// Thin wrapper around fetch for the alerts + assets + propagation API.
// All requests go through Vite's /api proxy -> FastAPI at 127.0.0.1:8001.

import propagationFixture from "../fixtures/propagation.json"

const BASE = "/api"

// Flip to false once Dev 1's /propagation/* endpoints are live and stable.
// Until then we fall back to the bundled fixture on 404.
const USE_MOCK_PROPAGATION_FALLBACK = true

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => "")
    const err = new Error(`${res.status} ${res.statusText}: ${text || path}`)
    err.status = res.status
    throw err
  }
  if (res.status === 204) return null
  return res.json()
}

/** Try the real API; fall back to fixture on 404 if mock fallback is enabled. */
async function requestWithMockFallback(path, mockValue) {
  try {
    return await request(path)
  } catch (exc) {
    if (USE_MOCK_PROPAGATION_FALLBACK && exc.status === 404) {
      console.info(`[mock] ${path} not implemented yet — using fixture`)
      return mockValue
    }
    throw exc
  }
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

export async function uploadAssetFromUrl({ url, title, description }) {
  return request(`/assets/from-url`, {
    method: "POST",
    body: JSON.stringify({ url, title, description: description ?? null }),
  })
}

// ---------------------------------------------------------------------------
// Case management
// ---------------------------------------------------------------------------

export function listComments(alertId) {
  return request(`/alerts/${alertId}/comments`)
}

export function addComment(alertId, { author, body }) {
  return request(`/alerts/${alertId}/comments`, {
    method: "POST",
    body: JSON.stringify({ author, body }),
  })
}

/**
 * Partial update. Pass fields you want to change. Pass `null` to clear a field
 * (e.g. `{ assigned_to: null }` to unassign).
 */
export function updateCase(alertId, { assigned_to, priority, due_date } = {}) {
  const payload = {}
  // Only include keys the caller explicitly passed, so PATCH semantics work
  // on the backend (it uses model_fields_set to distinguish null vs omitted).
  if (assigned_to !== undefined) payload.assigned_to = assigned_to
  if (priority !== undefined) payload.priority = priority
  if (due_date !== undefined) payload.due_date = due_date

  return request(`/alerts/${alertId}/case`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  })
}

// ---------------------------------------------------------------------------
// Propagation (Dev 1's spec — mocked until backend is live)
// ---------------------------------------------------------------------------

export function getPropagationGraph(matchId) {
  return requestWithMockFallback(
    `/propagation/${matchId}/graph`,
    propagationFixture.graph,
  )
}

export function getPropagationTimeline(matchId) {
  return requestWithMockFallback(
    `/propagation/${matchId}/timeline`,
    propagationFixture.timeline,
  )
}

export function getAssetPropagationSummary(assetId) {
  return requestWithMockFallback(
    `/propagation/${assetId}/summary`,
    propagationFixture.summary,
  )
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

export function getDashboardStats({ windowDays = 7 } = {}) {
  const params = new URLSearchParams({ window_days: windowDays })
  return request(`/stats/dashboard?${params}`)
}