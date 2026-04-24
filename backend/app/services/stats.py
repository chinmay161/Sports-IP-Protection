# app/services/stats.py
"""Aggregations for the dashboard landing page.

All queries are against the `alerts` table (and a minimal asset count).
Intentionally not touching Dev 1's `matches` table — that's a separate
detection dataset; we can unify later.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert
from app.models.asset import Asset


# Status buckets
_RESOLVED_STATUSES = {"resolved"}
_ACTIVE_STATUSES = {"open", "acknowledged", "dmca_initiated"}


def _day_key(dt: datetime) -> str:
    """YYYY-MM-DD key for grouping. Uses the alert's created_at date."""
    return dt.date().isoformat()


async def compute_dashboard_stats(db: AsyncSession, time_window_days: int = 7) -> dict[str, Any]:
    """Return all numbers the dashboard needs in a single round trip.

    time_window_days controls the bucketed time-series only; the top-line
    KPIs are always all-time unless noted (e.g. mean_time_to_action).
    """
    now = datetime.utcnow()
    # Start the window so the last day is *today*. For a 7-day window that's
    # today + 6 prior days.
    today = now.date()
    window_start = datetime.combine(today - timedelta(days=time_window_days - 1), datetime.min.time())

    # Pull every alert once; aggregate in Python. At the scale we care about
    # (thousands, not millions), this is fine and keeps the code obvious.
    # If/when we scale, swap to SQL GROUP BYs.
    result = await db.execute(select(Alert))
    alerts = list(result.scalars().all())

    # --- Top-line KPIs ----------------------------------------------------

    total_alerts = len(alerts)
    active = [a for a in alerts if a.status in _ACTIVE_STATUSES]
    resolved = [a for a in alerts if a.status in _RESOLVED_STATUSES]
    critical_open = [
        a for a in active if a.severity_label == "critical"
    ]

    takedown_rate = (
        len([a for a in alerts if a.status in ("dmca_initiated", "resolved")]) / total_alerts
        if total_alerts
        else 0.0
    )

    resolved_durations_s = [
        (a.updated_at - a.created_at).total_seconds()
        for a in resolved
        if a.updated_at and a.created_at
    ]
    mean_time_to_resolution_s = (
        sum(resolved_durations_s) / len(resolved_durations_s)
        if resolved_durations_s
        else None
    )

    # --- Time series: alerts created per day over the window -------------

    window_alerts = [a for a in alerts if a.created_at >= window_start]

    series: list[dict[str, Any]] = []
    for offset in range(time_window_days):
        day = (window_start + timedelta(days=offset)).date()
        key = day.isoformat()
        day_alerts = [a for a in window_alerts if a.created_at.date() == day]
        series.append(
            {
                "date": key,
                "total": len(day_alerts),
                "critical": sum(1 for a in day_alerts if a.severity_label == "critical"),
                "high":     sum(1 for a in day_alerts if a.severity_label == "high"),
                "medium":   sum(1 for a in day_alerts if a.severity_label == "medium"),
                "low":      sum(1 for a in day_alerts if a.severity_label == "low"),
            }
        )

    # --- Severity + platform breakdowns (all-time) -----------------------

    severity_counts = Counter(a.severity_label for a in alerts)
    platform_counts = Counter((a.platform or "unknown") for a in alerts)

    # Top 6 platforms by volume
    top_platforms = [
        {"platform": p, "count": c}
        for p, c in platform_counts.most_common(6)
    ]

    # --- Priority queue: 5 most urgent unresolved ------------------------

    def _priority_sort_key(a: Alert) -> tuple:
        # Sort order: critical > high > medium > low; then urgent > high > medium > low; then newest first.
        severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(a.severity_label, 4)
        priority_rank = {"urgent": 0, "high": 1, "medium": 2, "low": 3}.get(a.priority, 4)
        # Newer first -> negative timestamp so ascending sort puts it at top
        return (severity_rank, priority_rank, -a.created_at.timestamp())

    queue = sorted(active, key=_priority_sort_key)[:5]
    priority_queue = [
        {
            "id": a.id,
            "severity_label": a.severity_label,
            "priority": a.priority,
            "platform": a.platform,
            "infringing_url": a.infringing_url,
            "assigned_to": a.assigned_to,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "status": a.status,
        }
        for a in queue
    ]

    # --- Asset count (for "assets protected" KPI) ------------------------

    asset_count = (await db.execute(select(func.count(Asset.id)))).scalar_one() or 0

    return {
        "generated_at": now.isoformat() + "Z",
        "time_window_days": time_window_days,
        "kpis": {
            "total_alerts": total_alerts,
            "active_alerts": len(active),
            "critical_open": len(critical_open),
            "assets_protected": asset_count,
            "takedown_rate": round(takedown_rate, 3),
            "mean_time_to_resolution_s": (
                round(mean_time_to_resolution_s) if mean_time_to_resolution_s else None
            ),
        },
        "severity_breakdown": {
            "critical": severity_counts.get("critical", 0),
            "high":     severity_counts.get("high",     0),
            "medium":   severity_counts.get("medium",   0),
            "low":      severity_counts.get("low",      0),
        },
        "top_platforms": top_platforms,
        "timeseries": series,
        "priority_queue": priority_queue,
    }