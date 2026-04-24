# app/workers/alert_subscriber.py
"""Background task: subscribe to `match.created` events, fan out to dashboard.

Started from FastAPI's lifespan. Runs for the life of the process.

Flow:
  Redis event arrives
    -> fetch the Alert row from the DB (DB is single source of truth)
    -> shape it into a dashboard-friendly dict
    -> broadcast to all WebSocket connections
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.db.session import SessionLocal
from app.models.alert import Alert
from app.services.broadcaster import manager
from app.services.events import CHANNEL_MATCH_CREATED, subscribe

logger = logging.getLogger(__name__)


def _serialize_alert(alert: Alert) -> dict[str, Any]:
    """Shape an Alert ORM row into the payload the dashboard expects."""
    return {
        "id": alert.id,
        "asset_id": alert.asset_id,
        "status": alert.status,
        "severity_score": alert.severity_score,
        "severity_label": alert.severity_label,
        "match_type": alert.match_type,
        "confidence": alert.confidence,
        "infringing_url": alert.infringing_url,
        "platform": alert.platform,
        "ai_reasoning": alert.ai_reasoning,
        "notified_email": alert.notified_email,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
        "updated_at": alert.updated_at.isoformat() if alert.updated_at else None,
    }


async def _handle_event(payload: dict[str, Any]) -> None:
    """Look up the alert referenced by the event and broadcast it."""
    alert_id = payload.get("alert_id") or payload.get("match_id")
    if not alert_id:
        logger.warning("event_missing_alert_id payload=%s", payload)
        return

    async with SessionLocal() as session:
        alert = await session.get(Alert, str(alert_id))
        if alert is None:
            # Race: event arrived before DB commit is visible, or alert was deleted.
            # We don't retry here; Dev 1's matcher should commit before publishing.
            logger.warning("alert_not_found_for_event alert_id=%s", alert_id)
            return

        message = {
            "type": "alert.created",
            "alert": _serialize_alert(alert),
        }
    reached = await manager.broadcast(message)
    logger.info("alert_broadcast alert_id=%s reached=%d", alert_id, reached)


async def run_alert_subscriber() -> None:
    """Main subscriber loop. Reconnects forever on Redis failure."""
    while True:
        try:
            async for event in subscribe(CHANNEL_MATCH_CREATED):
                try:
                    await _handle_event(event)
                except Exception:
                    logger.exception("alert_handler_failed event=%s", event)
        except asyncio.CancelledError:
            logger.info("alert_subscriber_cancelled")
            raise
        except Exception as exc:
            logger.exception("alert_subscriber_error error=%s reconnecting_in=5s", exc)
            await asyncio.sleep(5)