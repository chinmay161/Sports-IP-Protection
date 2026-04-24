# app/services/events.py
"""Redis pub/sub helpers for real-time event distribution.

Why a separate module:
- Keeps the raw redis client wrapped in one place so callers don't import `redis` directly.
- Lets us add serialization, retries, or observability in a single spot later.
- Makes testing easier: mock one module, not scattered `redis.Redis()` calls.

Channels:
- `match.created`  Published by Dev 1 (Matcher) after inserting a new match.
                   Payload is intentionally minimal; subscribers fetch the full
                   row from Postgres/SQLite using `match_id` (or `alert_id`).
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import redis.asyncio as redis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

CHANNEL_MATCH_CREATED = "match.created"


_redis_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    """Return a process-wide async Redis client. Lazy-initialized."""
    global _redis_client
    if _redis_client is None:
        settings = get_settings()
        _redis_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


async def publish(channel: str, payload: dict[str, Any]) -> int:
    """Publish a JSON payload to a channel. Returns number of subscribers reached."""
    client = get_redis()
    message = json.dumps(payload, default=str)
    delivered = await client.publish(channel, message)
    logger.info("event_published channel=%s delivered=%d", channel, delivered)
    return delivered


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
        await _redis_client.aclose()
        _redis_client = None