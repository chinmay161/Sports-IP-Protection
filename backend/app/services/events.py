# app/services/events.py
"""Redis pub/sub helpers for real-time event distribution.

Why a separate module:
- Keeps the raw redis client wrapped in one place so callers don't import `redis` directly.
- Lets us add serialization, retries, or observability in a single spot later.
- Makes testing easier: mock one module, not scattered `redis.Redis()` calls.

Production resilience: if Redis isn't reachable (e.g. on a single-container
deploy without a Redis sidecar), publish() degrades gracefully — it logs and
returns 0 rather than crashing the request. WebSocket subscribers won't get
real-time pushes, but every HTTP endpoint keeps working.

Channels:
- `match.created`  Published by Dev 1 (Matcher) after inserting a new match.
                   Payload is intentionally minimal; subscribers fetch the full
                   row from Postgres/SQLite using `match_id` (or `alert_id`).
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, AsyncIterator

import redis.asyncio as redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

CHANNEL_MATCH_CREATED = "match.created"
CHANNEL_ASSET_STATUS_CHANGED = "asset.status_changed"
CHANNEL_ALERT_UPDATED = "alert.updated"


_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Return an async Redis client bound to the current event loop.

    FastAPI (one long-lived loop) reuses the client across calls.
    Celery tasks create a new loop per task via asyncio.run(), so the cached
    client's loop becomes closed; we detect that and rebuild.
    """
    global _redis_client
    if _redis_client is not None:
        try:
            current_loop = asyncio.get_event_loop()
            if current_loop.is_closed():
                _redis_client = None
        except RuntimeError:
            _redis_client = None

    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def publish(channel: str, payload: dict[str, Any]) -> int:
    """Publish a JSON payload to a channel. Returns subscriber count, or 0
    if Redis is unreachable.

    We intentionally swallow Redis errors here. The HTTP request that
    triggered the publish has already done its real work (DB write, etc.).
    Failing real-time push is acceptable; failing the user-facing request
    because pub/sub is down is not.
    """
    try:
        client = get_redis()
        message = json.dumps(payload, default=str)
        delivered = await client.publish(channel, message)
        logger.info("event_published channel=%s delivered=%d", channel, delivered)
        return delivered
    except Exception as exc:
        # ConnectionError, TimeoutError, network blips — none should fail the
        # caller. Log once at debug level (we already log the connection
        # failures from the subscriber loop at warning level).
        logger.debug("event_publish_failed channel=%s error=%s", channel, exc)
        return 0


async def subscribe(channel: str) -> AsyncIterator[dict[str, Any]]:
    """Async generator yielding decoded JSON payloads from a channel.

    Handles JSON decoding errors by logging and skipping malformed messages.
    Caller is responsible for cancellation / cleanup (use `async for ... in`).
    """
    client = get_redis()
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    logger.info("subscriber_started channel=%s", channel)
    try:
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            raw = message.get("data")
            try:
                yield json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                logger.warning("malformed_event channel=%s raw=%r", channel, raw)
                continue
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
        logger.info("subscriber_stopped channel=%s", channel)


async def close_redis() -> None:
    """Close the module-level client on shutdown."""
    global _redis_client
    if _redis_client is not None:
        try:
            await _redis_client.aclose()
        except Exception:
            pass
        _redis_client = None