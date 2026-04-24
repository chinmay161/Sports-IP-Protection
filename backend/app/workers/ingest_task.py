# app/workers/ingest_task.py
import asyncio
import logging
import sys
from uuid import UUID

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.services.asset import refresh_aggregate_status
from app.services.events import CHANNEL_ASSET_STATUS_CHANGED, publish
from app.services.fingerprint import FingerprintService

try:
    from celery import Celery
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    class Celery:  # type: ignore[override]
        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def task(self, *args, **kwargs):
            def decorator(func):
                func.delay = lambda **delay_kwargs: type(
                    "AsyncResultStub",
                    (),
                    {"id": f"local-{delay_kwargs.get('asset_id', 'task')}"},
                )()
                return func

            return decorator


settings = get_settings()
logger = logging.getLogger(__name__)
celery_app = Celery(
    "sports_ip_protection",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

if sys.platform.startswith("win"):
    celery_app.conf.update(worker_pool="solo", worker_concurrency=1)


async def _notify_asset_status_changed(asset_id: str) -> None:
    """Best-effort publish. Never let a pub/sub failure crash the ingest task.

    Creates a fresh Redis client per call (we're inside asyncio.run() which
    gets a brand new event loop per Celery task; module-level client caching
    would bind to a closed loop on subsequent tasks).
    """
    import json
    import redis.asyncio as redis

    from app.core.config import get_settings
    from app.services.events import CHANNEL_ASSET_STATUS_CHANGED

    client = redis.from_url(
        get_settings().redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    try:
        delivered = await client.publish(
            CHANNEL_ASSET_STATUS_CHANGED,
            json.dumps({"asset_id": asset_id}),
        )
        logger.info(
            "asset_status_published asset_id=%s delivered=%d",
            asset_id, delivered,
        )
    except Exception:
        logger.exception("asset_status_publish_failed asset_id=%s", asset_id)
    finally:
        try:
            await client.aclose()
        except Exception:
            pass

class TransientIngestError(Exception):
    """Retryable ingest error."""


@celery_app.task(
    bind=True,
    autoretry_for=(TransientIngestError, OSError, ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 3},
)
def ingest_asset(self, asset_id: str, video_path: str) -> dict[str, str]:
    return asyncio.run(_ingest_asset_impl(asset_id=asset_id, video_path=video_path))


async def _ingest_asset_impl(asset_id: str, video_path: str) -> dict[str, str]:
    service = FingerprintService()
    async with SessionLocal() as session:
        asset = await session.get(Asset, asset_id)
        if asset is None:
            raise ValueError(f"Asset {asset_id} not found")

        if hasattr(asset, "fingerprint_status"):
            asset.fingerprint_status = "processing"
            refresh_aggregate_status(asset)
        else:
            asset.status = "processing"
        await session.commit()
        await _notify_asset_status_changed(asset_id)

        try:
            await service.generate(video_path=video_path, asset_id=UUID(asset_id))
        except (OSError, ConnectionError, TimeoutError) as exc:
            if hasattr(asset, "fingerprint_status"):
                asset.fingerprint_status = "failed"
                refresh_aggregate_status(asset)
            else:
                asset.status = "failed"
            await session.commit()
            await _notify_asset_status_changed(asset_id)
            raise TransientIngestError(str(exc)) from exc
        except Exception:
            logger.exception("fingerprint_ingest_failed asset_id=%s", asset_id)
            if hasattr(asset, "fingerprint_status"):
                asset.fingerprint_status = "failed"
                refresh_aggregate_status(asset)
            else:
                asset.status = "failed"
            await session.commit()
            await _notify_asset_status_changed(asset_id)
            raise

        if hasattr(asset, "fingerprint_status"):
            asset.fingerprint_status = "ready"
            refresh_aggregate_status(asset)
        else:
            asset.status = "ready"
        await session.commit()
        await _notify_asset_status_changed(asset_id)
        return {"asset_id": asset_id, "status": asset.status}


@celery_app.task
def finalize_asset(results: list[dict[str, str]], asset_id: str) -> dict[str, str]:
    return asyncio.run(_finalize_asset_impl(asset_id=asset_id))


async def _finalize_asset_impl(asset_id: str) -> dict[str, str]:
    async with SessionLocal() as session:
        asset = await session.get(Asset, asset_id)
        if asset is None:
            raise ValueError(f"Asset {asset_id} not found")
        refresh_aggregate_status(asset)
        await session.commit()
        await _notify_asset_status_changed(asset_id)
        return {"asset_id": asset_id, "status": asset.status}