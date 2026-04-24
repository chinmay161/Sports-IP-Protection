# app/workers/event_subscriber.py
"""Background task: subscribe to all real-time event channels and fan out
to dashboard WebSocket clients.

Message envelope pushed to WS:
    { "type": "<event-name>", "payload": { ... } }

Currently handles:
    match.created         -> alert.created
    asset.status_changed  -> asset.status_changed
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.db.session import SessionLocal
from app.models.alert import Alert
from app.models.asset import Asset
from app.services.broadcaster import manager
from app.services.events import (
    CHANNEL_ASSET_STATUS_CHANGED,
    CHANNEL_MATCH_CREATED,
    get_redis,
)

logger = logging.getLogger(__name__)


def _serialize_alert(alert: Alert) -> dict[str, Any]:
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


def _serialize_asset(asset: Asset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "title": asset.title,
        "description": asset.description,
        "status": asset.status,
        "fingerprint_status": asset.fingerprint_status,
        "watermark_status": asset.watermark_status,
        "video_path": asset.video_path,
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
        "updated_at": asset.updated_at.isoformat() if asset.updated_at else None,
    }


async def _handle_match_created(payload: dict[str, Any]) -> None:
    alert_id = payload.get("alert_id") or payload.get("match_id")
    if not alert_id:
        logger.warning("match_event_missing_id payload=%s", payload)
        return
    async with SessionLocal() as session:
        alert = await session.get(Alert, str(alert_id))
    if alert is None:
        logger.warning("alert_not_found_for_event alert_id=%s", alert_id)
        return
    reached = await manager.broadcast(
        {"type": "alert.created", "alert": _serialize_alert(alert)}
    )
    logger.info("alert_broadcast alert_id=%s reached=%d", alert_id, reached)


async def _handle_asset_status_changed(payload: dict[str, Any]) -> None:
    asset_id = payload.get("asset_id")
    if not asset_id:
        logger.warning("asset_event_missing_id payload=%s", payload)
        return
    async with SessionLocal() as session:
        asset = await session.get(Asset, str(asset_id))
    if asset is None:
        logger.warning("asset_not_found_for_event asset_id=%s", asset_id)
        return
    reached = await manager.broadcast(
        {"type": "asset.status_changed", "asset": _serialize_asset(asset)}
    )
    logger.info("asset_broadcast asset_id=%s reached=%d", asset_id, reached)


HANDLERS = {
    CHANNEL_MATCH_CREATED: _handle_match_created,
    CHANNEL_ASSET_STATUS_CHANGED: _handle_asset_status_changed,
}


async def run_event_subscriber() -> None:
    """Main subscriber loop. Subscribes to all channels on one connection and
    dispatches to per-channel handlers. Reconnects forever on Redis failure."""
    channels = list(HANDLERS.keys())
    while True:
        pubsub = None
        try:
            client = get_redis()
            pubsub = client.pubsub()
            await pubsub.subscribe(*channels)
            logger.info("event_subscriber_ready channels=%s", channels)

            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                channel = message.get("channel")
                raw = message.get("data")
                handler = HANDLERS.get(channel)
                if handler is None:
                    logger.warning("event_no_handler channel=%s", channel)
                    continue
                try:
                    import json
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    logger.warning("malformed_event channel=%s raw=%r", channel, raw)
                    continue
                try:
                    await handler(payload)
                except Exception:
                    logger.exception("event_handler_failed channel=%s payload=%s", channel, payload)

        except asyncio.CancelledError:
            logger.info("event_subscriber_cancelled")
            if pubsub is not None:
                try:
                    await pubsub.unsubscribe()
                    await pubsub.aclose()
                except Exception:
                    pass
            raise
        except Exception as exc:
            logger.exception("event_subscriber_error error=%s reconnecting_in=5s", exc)
            await asyncio.sleep(5)