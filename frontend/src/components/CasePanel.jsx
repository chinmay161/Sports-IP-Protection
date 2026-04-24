// src/components/CasePanel.jsx
import { useCallback, useEffect, useState } from "react"

import { addComment, listComments, updateCase } from "../api/client.js"
import USERS from "../fixtures/users.json"

const PRIORITIES = ["low", "medium", "high", "urgent"]

const PRIORITY_STYLES = {
  low:    "bg-slate-500/15 text-slate-300 ring-slate-500/30",
  medium: "bg-cyan-500/15 text-cyan-300 ring-cyan-500/40",
  high:   "bg-orange-500/15 text-orange-300 ring-orange-500/40",
  urgent: "bg-red-500/15 text-red-300 ring-red-500/40",
}

function formatWhen(iso) {
  if (!iso) return ""
  return new Date(iso).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  })
}

function userLabel(email) {
  if (!email) return "Unassigned"
  const user = USERS.find((u) => u.email === email)
  return user ? `${user.name} · ${user.role}` : email
}

function CommentItem({ comment }) {
  const isSystem = comment.kind === "system"
  if (isSystem) {
    return (
      <li className="flex items-center gap-2 text-xs text-slate-500">
        <span className="h-1 w-1 shrink-0 rounded-full bg-slate-600" />
        <span className="italic">{comment.body}</span>
        <span className="ml-auto text-[10px] text-slate-600">
          {formatWhen(comment.created_at)} · {comment.author}
        </span>
      </li>
    )
  }
  return (
    <li className="rounded-md border border-slate-800 bg-slate-950/60 p-2.5">
      <div className="mb-1 flex items-center justify-between">
        <span className="text-xs font-medium text-slate-200">{comment.author}</span>
        <span className="text-[10px] text-slate-500">{formatWhen(comment.created_at)}</span>
      </div>
      <div className="whitespace-pre-wrap text-xs text-slate-300">{comment.body}</div>
    </li>
  )
}

/**
 * Renders inside an expanded AlertCard.
 *
 * Props:
 *   alert        the current alert
 *   onUpdated    callback(updatedAlert) after PATCH succeeds — used to sync AlertFeed state
 */
export default function CasePanel({ alert, onUpdated }) {
  const [comments, setComments] = useState([])
  const [loadingComments, setLoadingComments] = useState(true)
  const [newComment, setNewComment] = useState("")
  const [posting, setPosting] = useState(false)
  const [err, setErr] = useState(null)
  const [busyField, setBusyField] = useState(null) // 'assign' | 'priority' | 'due' | null

  // Current "author" for new comments — if/when Auth0 is real, this would come
  // from the user session. For now, first fixture user.
  const currentAuthor = USERS[0].email

  const loadComments = useCallback(async () => {
    setLoadingComments(true)
    setErr(null)
    try {
      const list = await listComments(alert.id)
      setComments(list)
    } catch (exc) {
      setErr(exc.message)
    } finally {
      setLoadingComments(false)
    }
  }, [alert.id])

  useEffect(() => {
    loadComments()
  }, [loadComments])

  // When the parent tells us the alert was updated via WebSocket, refresh comments
  // too — a status/case change on the backend generates a new system comment.
  useEffect(() => {
    loadComments()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [alert.updated_at])

  const runFieldUpdate = async (fieldKey, patch) => {
    setBusyField(fieldKey)
    setErr(null)
    try {
      const updated = await updateCase(alert.id, patch)
      onUpdated?.(updated)
      // Comments refresh via the updated_at effect above.
    } catch (exc) {
      setErr(exc.message)
    } finally {
      setBusyField(null)
    }
  }

  const handleAssigneeChange = (e) => {
    const value = e.target.value
    // Empty string from dropdown = explicit unassign, sent as null
    runFieldUpdate("assign", { assigned_to: value === "" ? null : value })
  }

  const handlePriorityChange = (e) => {
    runFieldUpdate("priority", { priority: e.target.value })
  }

  const handleDueDateChange = (e) => {
    const value = e.target.value
    runFieldUpdate("due", { due_date: value === "" ? null : new Date(value).toISOString() })
  }

  const submitComment = async () => {
    const body = newComment.trim()
    if (!body) return
    setPosting(true)
    setErr(null)
    try {
      await addComment(alert.id, { author: currentAuthor, body })
      setNewComment("")
      await loadComments()
    } catch (exc) {
      setErr(exc.message)
    } finally {
      setPosting(false)
    }
  }

  // Due date value for <input type="datetime-local"> needs "YYYY-MM-DDTHH:mm"
  const dueDateInputValue = alert.due_date
    ? new Date(alert.due_date).toISOString().slice(0, 16)
    : ""

  return (
    <div className="mt-3 space-y-4 rounded-lg border border-slate-800 bg-slate-950/60 p-4">
      {/* Case fields row */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div>
          <label className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Assignee
          </label>
          <select
            value={alert.assigned_to ?? ""}
            onChange={handleAssigneeChange}
            disabled={busyField === "assign"}
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-200 focus:border-slate-500 focus:outline-none disabled:opacity-50"
          >
            <option value="">Unassigned</option>
            {USERS.map((u) => (
              <option key={u.email} value={u.email}>
                {u.name} · {u.role}
              </option>
            ))}
          </select>
          <div className="mt-1 text-[10px] text-slate-500">
            {userLabel(alert.assigned_to)}
          </div>
        </div>

        <div>
          <label className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Priority
          </label>
          <select
            value={alert.priority ?? "medium"}
            onChange={handlePriorityChange}
            disabled={busyField === "priority"}
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-200 focus:border-slate-500 focus:outline-none disabled:opacity-50"
          >
            {PRIORITIES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <span className={`mt-1 inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ring-1 ring-inset ${PRIORITY_STYLES[alert.priority ?? "medium"]}`}>
            {alert.priority ?? "medium"}
          </span>
        </div>

        <div>
          <label className="block text-[10px] font-semibold uppercase tracking-wider text-slate-500">
            Due date
          </label>
          <input
            type="datetime-local"
            value={dueDateInputValue}
            onChange={handleDueDateChange}
            disabled={busyField === "due"}
            className="mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-200 focus:border-slate-500 focus:outline-none disabled:opacity-50"
          />
          {alert.due_date && (
            <button
              onClick={() => runFieldUpdate("due", { due_date: null })}
              className="mt-1 text-[10px] text-slate-500 hover:text-slate-300"
            >
              clear
            </button>
          )}
        </div>
      </div>

      {err && (
        <p className="rounded border border-red-500/40 bg-red-500/10 px-2.5 py-1.5 text-xs text-red-300">
          {err}
        </p>
      )}

      {/* Comment thread */}
      <div>
        <div className="mb-2 flex items-center gap-2">
          <span className="text-xs font-semibold text-slate-300">Activity</span>
          <span className="text-[10px] text-slate-500">{comments.length} items</span>
        </div>

        {loadingComments ? (
          <div className="text-xs text-slate-500">Loading...</div>
        ) : comments.length === 0 ? (
          <div className="text-xs text-slate-500">No activity yet.</div>
        ) : (
          <ul className="space-y-1.5">
            {comments.map((c) => (
              <CommentItem key={c.id} comment={c} />
            ))}
          </ul>
        )}

        <div className="mt-3 flex gap-2">
          <input
            type="text"
            value={newComment}
            onChange={(e) => setNewComment(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !posting) {
                e.preventDefault()
                submitComment()
              }
            }}
            placeholder="Add a comment..."
            className="flex-1 rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-xs text-slate-200 focus:border-slate-500 focus:outline-none"
          />
          <button
            onClick={submitComment}
            disabled={posting || !newComment.trim()}
            className="rounded-md bg-cyan-500 px-3 py-1.5 text-xs font-semibold text-slate-950 transition hover:bg-cyan-400 disabled:opacity-50"
          >
            {posting ? "..." : "Post"}
          </button>
        </div>
      </div>
    </div>
  )
}