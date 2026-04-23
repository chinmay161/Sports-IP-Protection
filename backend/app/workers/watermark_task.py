import asyncio
import logging
from uuid import UUID

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.services.asset import refresh_aggregate_status
from app.services.watermark import WatermarkService, decode_watermark_key
from app.workers.ingest_task import celery_app


logger = logging.getLogger(__name__)


class TransientWatermarkError(Exception):
    """Retryable watermark error."""


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def watermark_asset(self, asset_id: str, payload: int, alpha: int = 8) -> dict[str, str]:
    try:
        return asyncio.run(_watermark_asset_impl(asset_id=asset_id, payload=payload, alpha=alpha))
    except (OSError, ConnectionError, TimeoutError, TransientWatermarkError) as exc:
        raise self.retry(exc=exc) from exc


async def _watermark_asset_impl(asset_id: str, payload: int, alpha: int = 8) -> dict[str, str]:
    current_settings = get_settings()
    if not current_settings.watermark_secret_key:
        raise RuntimeError("WATERMARK_SECRET_KEY is required")
    key = decode_watermark_key(current_settings.watermark_secret_key)
    service = WatermarkService()

    async with SessionLocal() as session:
        asset = await session.get(Asset, asset_id)
        if asset is None:
            raise ValueError(f"Asset {asset_id} not found")

        asset.watermark_status = "processing"
        refresh_aggregate_status(asset)
        await session.commit()

        try:
            await service.embed_video(
                video_path=asset.video_path,
                asset_id=UUID(asset_id),
                payload=payload,
                key=key,
                alpha=alpha,
            )
        except (OSError, ConnectionError, TimeoutError) as exc:
            asset.watermark_status = "failed"
            refresh_aggregate_status(asset)
            await session.commit()
            raise TransientWatermarkError(str(exc)) from exc
        except Exception:
            logger.exception("watermark_asset_failed asset_id=%s", asset_id)
            asset.watermark_status = "failed"
            refresh_aggregate_status(asset)
            await session.commit()
            raise

        asset.watermark_status = "ready"
        refresh_aggregate_status(asset)
        await session.commit()
        return {"asset_id": asset_id, "status": asset.status}
