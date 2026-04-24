# app/services/case.py
"""Case management service: comments, assignment, priority, due date.

System comments (kind='system') are auto-generated when alert status or case
fields change, so the activity log reads as a single coherent timeline.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.comment import CaseComment


VALID_PRIORITIES = {"low", "medium", "high", "urgent"}


async def list_comments(
    db: AsyncSession, alert_id: str, limit: int = 200
) -> list[CaseComment]:
    stmt = (
        select(CaseComment)
        .where(CaseComment.alert_id == alert_id)
        .order_by(desc(CaseComment.created_at))
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def add_comment(
    db: AsyncSession,
    alert_id: str,
    author: str,
    body: str,
    kind: str = "user",
) -> CaseComment:
    comment = CaseComment(
        alert_id=alert_id,
        author=author,
        body=body,
        kind=kind,
    )
    db.add(comment)
    await db.commit()
    await db.refresh(comment)
    return comment


async def update_case_fields(
    db: AsyncSession,
    alert: Alert,
    *,
    actor: str,
    assigned_to: str | None = None,
    priority: str | None = None,
    due_date: datetime | None = None,
    clear_assigned: bool = False,
    clear_due_date: bool = False,
) -> tuple[Alert, list[CaseComment]]:
    """Apply partial case updates and generate system comments for each change.

    Returns the refreshed alert and the list of system comments created.
    Caller commits. Use clear_* flags to explicitly null a field (vs "don't touch").
    """
    system_events: list[tuple[str, str]] = []  # (author, body) pairs

    if clear_assigned or assigned_to is not None:
        new_value = None if clear_assigned else assigned_to
        if alert.assigned_to != new_value:
            old = alert.assigned_to or "unassigned"
            new = new_value or "unassigned"
            system_events.append((actor, f"Assignment: {old} → {new}"))
            alert.assigned_to = new_value

    if priority is not None:
        if priority not in VALID_PRIORITIES:
            raise ValueError(f"Invalid priority: {priority}. Must be one of {VALID_PRIORITIES}.")
        if alert.priority != priority:
            system_events.append((actor, f"Priority: {alert.priority} → {priority}"))
            alert.priority = priority

    if clear_due_date or due_date is not None:
        new_value = None if clear_due_date else due_date
        if alert.due_date != new_value:
            old = alert.due_date.isoformat() if alert.due_date else "none"
            new = new_value.isoformat() if new_value else "none"
            system_events.append((actor, f"Due date: {old} → {new}"))
            alert.due_date = new_value

    created_comments: list[CaseComment] = []
    for author, body in system_events:
        c = CaseComment(alert_id=alert.id, author=author, body=body, kind="system")
        db.add(c)
        created_comments.append(c)

    await db.commit()
    await db.refresh(alert)
    for c in created_comments:
        await db.refresh(c)
    return alert, created_comments


async def log_status_change(
    db: AsyncSession, alert: Alert, *, actor: str, old_status: str, new_status: str
) -> CaseComment:
    """Append a system comment for a status transition. Caller should commit
    the alert update in the same transaction as this add, or pass an already-
    committed alert. We commit the comment independently to keep this simple."""
    c = CaseComment(
        alert_id=alert.id,
        author=actor,
        body=f"Status: {old_status} → {new_status}",
        kind="system",
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c