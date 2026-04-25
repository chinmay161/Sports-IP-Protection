# app/workers/visual_task.py
"""Celery task wrappers for visual discovery.

The hard work lives in app.services.visual_discovery.VisualDiscoveryService.
This module's job is to invoke that service from a Celery worker and publish
status events for the dashboard.
"""
import asyncio
import json
import logging
from uuid import UUID

from app.core.celery import celery_app
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.visual_discovery import VisualDiscoveryService


logger = logging.getLogger(__name__)


CHANNEL_VISUAL_DISCOVERY = "visual.discovery"


async def _publish_visual_event(asset_id: str, status: str, candidate_count: int = 0) -> None:
    """Best-effort pub/sub. Same fresh-client pattern as ingest task."""
    import redis.asyncio as redis

    client = redis.from_url(
        get_settings().redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    try:
        await client.publish(
            CHANNEL_VISUAL_DISCOVERY,
            json.dumps(
                {
                    "asset_id": asset_id,
                    "status": status,
                    "candidate_count": candidate_count,
                }
            ),
        )
    except Exception:
        logger.exception("visual_event_publish_failed asset_id=%s", asset_id)
    finally:
        try:
            await client.aclose()
        except Exception:
            pass


@celery_app.task(bind=True, max_retries=2, default_retry_delay=60)
def discover_visual_candidates(
    self,
    asset_id: str,
    query: str | None = None,
    max_candidates: int | None = None,
) -> dict[str, object]:
    """Run visual discovery for an asset.

    Returns {asset_id, candidate_count}. The actual VisualCandidate rows are
    persisted to the DB by the service.
    """
    return asyncio.run(_discover_impl(asset_id, query, max_candidates))


async def _discover_impl(
    asset_id: str,
    query: str | None,
    max_candidates: int | None,
) -> dict[str, object]:
    await _publish_visual_event(asset_id, "discovering")

    async with SessionLocal() as session:
        try:
            service = VisualDiscoveryService(session)
            candidates = await service.discover(
                asset_id=UUID(asset_id),
                query=query or "",
                max_candidates=max_candidates,
            )
            count = len(candidates)
            logger.info(
                "visual_discovery_complete asset_id=%s candidates=%d query=%r",
                asset_id, count, query,
            )
            await _publish_visual_event(asset_id, "complete", candidate_count=count)
            return {"asset_id": asset_id, "candidate_count": count}
        except Exception:
            logger.exception("visual_discovery_failed asset_id=%s", asset_id)
            await _publish_visual_event(asset_id, "failed")
            raise