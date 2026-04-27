import asyncio
import logging
import time
from uuid import UUID

from sqlalchemy import select

try:
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - dependency may be absent in lightweight test envs
    class ClientError(Exception):  # type: ignore[no-redef]
        pass

from app.core.celery import celery_app
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.live_stream import LiveStream
from app.services.live_stream import LiveStreamService, elapsed_ms, get_suspect_urls


logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=5, default_retry_delay=5)
def watermark_new_segments(self, stream_id: str, segment_names: list[str], payload: int) -> dict[str, int]:
    """Watermark newly arrived HLS segments.

    Production upgrade path: trigger this from S3 Event Notification -> SNS/SQS
    when a .ts object lands, rather than waiting for beat-style polling.
    """
    started = time.perf_counter()
    try:
        result = asyncio.run(_watermark_new_segments_impl(stream_id, segment_names, payload))
        logger.info(
            "live_watermark_new_segments stream_id=%s segment_count=%d elapsed_ms=%d",
            stream_id,
            len(segment_names),
            elapsed_ms(started),
        )
        return result
    except (ClientError, RuntimeError, OSError) as exc:
        raise self.retry(exc=exc, countdown=5 * (2 ** self.request.retries)) from exc


async def _watermark_new_segments_impl(stream_id: str, segment_names: list[str], payload: int) -> dict[str, int]:
    watermarked = 0
    skipped = 0
    async with SessionLocal() as db:
        for segment_name in segment_names:
            row = await LiveStreamService.watermark_segment(UUID(stream_id), segment_name, payload, db)
            if row is None:
                skipped += 1
            else:
                watermarked += 1
    return {"watermarked": watermarked, "skipped": skipped}


@celery_app.task(bind=True, max_retries=3)
def poll_suspect_streams(self, stream_id: str, suspect_urls: list[str] | None = None) -> dict[str, int]:
    try:
        result = asyncio.run(_poll_suspect_streams_impl(stream_id, suspect_urls))
    except Exception as exc:
        raise self.retry(exc=exc, countdown=5 * (2 ** self.request.retries)) from exc

    if result["active"]:
        settings = get_settings()
        apply_async = getattr(poll_suspect_streams, "apply_async", None)
        if apply_async is not None:
            apply_async(args=[stream_id, suspect_urls], countdown=settings.inbound_poll_interval_s)
        else:  # pragma: no cover - only used by the local Celery stub
            poll_suspect_streams.delay(stream_id, suspect_urls)
    return result


async def _poll_suspect_streams_impl(stream_id: str, suspect_urls: list[str] | None) -> dict[str, int]:
    async with SessionLocal() as db:
        stream = await db.get(LiveStream, stream_id)
        if stream is None or stream.status != "active":
            logger.info("live_poll_skipped_inactive stream_id=%s", stream_id)
            return {"active": 0, "urls": 0, "matches": 0, "violations_triggered": 0}

    urls = suspect_urls or await get_suspect_urls(UUID(stream_id))
    results = await asyncio.gather(
        *[_scan_url(stream_id, url) for url in urls],
        return_exceptions=True,
    )

    matches = 0
    violations_triggered = 0
    for result in results:
        if isinstance(result, Exception):
            logger.warning("live_poll_url_failed stream_id=%s error=%s", stream_id, result)
            continue
        if result is not None:
            matches += 1
            if result.status == "dmca_sent":
                violations_triggered += 1

    async with SessionLocal() as db:
        stream = await db.get(LiveStream, stream_id)
        active = int(stream is not None and stream.status == "active")

    logger.info(
        "live_poll_suspect_streams stream_id=%s urls=%d matches=%d violations_triggered=%d",
        stream_id,
        len(urls),
        matches,
        violations_triggered,
    )
    return {
        "active": active,
        "urls": len(urls),
        "matches": matches,
        "violations_triggered": violations_triggered,
    }


async def _scan_url(stream_id: str, suspect_url: str):
    async with SessionLocal() as db:
        return await LiveStreamService.scan_suspect_stream(suspect_url, UUID(stream_id), db)


@celery_app.task
def monitor_live_streams() -> dict[str, int]:
    return asyncio.run(_monitor_live_streams_impl())


async def _monitor_live_streams_impl() -> dict[str, int]:
    async with SessionLocal() as db:
        result = await db.execute(select(LiveStream).where(LiveStream.status == "active"))
        streams = result.scalars().all()

    for stream in streams:
        urls = await get_suspect_urls(UUID(stream.id))
        poll_suspect_streams.delay(str(stream.id), urls)

    logger.info("live_monitor_streams active_count=%d", len(streams))
    return {"active_streams": len(streams)}
