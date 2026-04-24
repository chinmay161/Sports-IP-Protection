import asyncio
import logging
import time
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from app.core.celery import celery_app
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.services.matcher import MatcherService


logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def scan_asset(self, asset_id: str, max_per_platform: int = 20):
    try:
        return asyncio.run(_scan_asset_impl(asset_id, max_per_platform))
    except (OSError, ConnectionError, TimeoutError) as exc:
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries)) from exc


async def _scan_asset_impl(asset_id: str, max_per_platform: int = 20) -> dict[str, object]:
    start = time.perf_counter()
    async with SessionLocal() as db:
        matches = await MatcherService.scan_all(UUID(asset_id), db, max_per_platform=max_per_platform)
        asset = await db.get(Asset, asset_id)
        if asset is not None and hasattr(asset, "last_scanned_at"):
            asset.last_scanned_at = datetime.now(UTC)
            await db.commit()

    elapsed = time.perf_counter() - start
    logger.info(
        "scan_asset_complete asset_id=%s matches_found=%d elapsed=%.2fs",
        asset_id,
        len(matches),
        elapsed,
    )
    return {"asset_id": asset_id, "matches_found": len(matches)}


@celery_app.task
def scan_all_assets() -> dict[str, int]:
    return asyncio.run(_scan_all_assets_impl())


async def _scan_all_assets_impl() -> dict[str, int]:
    async with SessionLocal() as db:
        result = await db.execute(select(Asset.id).where(Asset.status == "ready"))
        asset_ids = result.scalars().all()

    for asset_id in asset_ids:
        scan_asset.delay(str(asset_id))

    logger.info("scan_all_assets_enqueued count=%d", len(asset_ids))
    return {"enqueued": len(asset_ids)}
