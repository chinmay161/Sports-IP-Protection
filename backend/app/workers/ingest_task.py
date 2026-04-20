import asyncio
import logging
from uuid import UUID

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.asset import Asset
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

        asset.status = "processing"
        await session.commit()

        try:
            await service.generate(video_path=video_path, asset_id=UUID(asset_id))
        except (OSError, ConnectionError, TimeoutError) as exc:
            asset.status = "failed"
            await session.commit()
            raise TransientIngestError(str(exc)) from exc
        except Exception:
            logger.exception("fingerprint_ingest_failed asset_id=%s", asset_id)
            asset.status = "failed"
            await session.commit()
            raise

        asset.status = "ready"
        await session.commit()
        return {"asset_id": asset_id, "status": "ready"}
