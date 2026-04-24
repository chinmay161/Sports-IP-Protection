# app/workers/download_task.py
"""URL-ingest download task.

Given (asset_id, url), uses yt-dlp to download the best available MP4/webm
into media_store/, updates the Asset row, then hands off to ingest_asset
(fingerprinting) via a Celery chain.

Publishes asset.status_changed at each transition so the dashboard follows
downloading -> processing -> ready in real time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from app.core.celery import celery_app
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models.asset import Asset
from app.services.asset import refresh_aggregate_status
from app.workers.ingest_task import ingest_asset

try:
    import yt_dlp  # type: ignore
except ImportError:  # pragma: no cover - only relevant when dep missing
    yt_dlp = None  # noqa: N816

logger = logging.getLogger(__name__)


async def _notify_asset_status_changed(asset_id: str) -> None:
    """Best-effort publish. Fresh Redis client per call (same pattern as ingest)."""
    try:
        import redis.asyncio as redis
        from app.services.events import CHANNEL_ASSET_STATUS_CHANGED

        client = redis.from_url(
            get_settings().redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        try:
            await client.publish(
                CHANNEL_ASSET_STATUS_CHANGED,
                json.dumps({"asset_id": asset_id}),
            )
        finally:
            await client.aclose()
    except Exception:
        logger.exception("asset_status_publish_failed asset_id=%s", asset_id)


class DownloadError(Exception):
    """Non-retryable download failure (bad URL, auth required, size cap, etc.)."""


MEDIA_ROOT = Path("media_store")


def _ydl_options(output_template: str, max_bytes: int) -> dict:
    """yt-dlp options tuned for single-video MP4-or-best extraction.

    Notes:
    - `format` picks the best muxed MP4 under max_bytes, falling back to best
      single stream. Keeps us out of merge territory (which needs ffmpeg flags).
    - `noplaylist=True` refuses to expand playlists.
    - `max_filesize` is yt-dlp's hard ceiling; yt-dlp aborts the download if
      the content-length or progress exceeds this.
    - `quiet` + `no_warnings` keep Celery logs clean; errors still raise.
    """
    return {
        "outtmpl": output_template,
        "format": f"best[filesize<{max_bytes}]/best",
        "max_filesize": max_bytes,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "nocheckcertificate": False,
        "retries": 2,
        "fragment_retries": 2,
        # Don't post-process. Raw file is what the fingerprinter wants.
        "postprocessors": [],
    }


def _run_yt_dlp(url: str, output_template: str, max_bytes: int) -> str:
    """Run yt-dlp synchronously. Returns the final filepath. Raises DownloadError."""
    if yt_dlp is None:
        raise DownloadError("yt-dlp is not installed")

    with yt_dlp.YoutubeDL(_ydl_options(output_template, max_bytes)) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            raise DownloadError(str(exc)) from exc

    # yt-dlp returns the chosen filepath in info["requested_downloads"][0]["filepath"]
    # for single-video extracts; fall back to prepare_filename on the info dict.
    downloads = info.get("requested_downloads") or []
    if downloads and downloads[0].get("filepath"):
        return downloads[0]["filepath"]

    with yt_dlp.YoutubeDL(_ydl_options(output_template, max_bytes)) as ydl:
        return ydl.prepare_filename(info)


@celery_app.task(bind=True)
def download_asset(self, asset_id: str, url: str) -> dict[str, str]:
    """Download the URL, update the Asset row, then chain ingest."""
    return asyncio.run(_download_asset_impl(asset_id=asset_id, url=url))


async def _download_asset_impl(asset_id: str, url: str) -> dict[str, str]:
    settings = get_settings()
    MEDIA_ROOT.mkdir(exist_ok=True)

    # Output template: media_store/<asset_id>.<ext>  (yt-dlp fills %(ext)s)
    output_template = str(MEDIA_ROOT / f"{asset_id}.%(ext)s")

    async with SessionLocal() as session:
        asset = await session.get(Asset, asset_id)
        if asset is None:
            raise ValueError(f"Asset {asset_id} not found")

        asset.download_status = "downloading"
        asset.status = "processing"
        await session.commit()
    await _notify_asset_status_changed(asset_id)

    try:
        # Blocking yt-dlp call offloaded to the default executor so we don't
        # block the asyncio loop (even though Celery solo pool makes this moot).
        loop = asyncio.get_event_loop()
        filepath = await loop.run_in_executor(
            None,
            _run_yt_dlp,
            url,
            output_template,
            settings.max_download_bytes,
        )

        # Verify file actually landed
        if not filepath or not os.path.exists(filepath):
            raise DownloadError(f"yt-dlp reported success but file missing: {filepath}")

        file_size = os.path.getsize(filepath)
        logger.info(
            "download_complete asset_id=%s path=%s size=%d",
            asset_id, filepath, file_size,
        )

        async with SessionLocal() as session:
            asset = await session.get(Asset, asset_id)
            asset.video_path = filepath
            asset.download_status = "ready"
            refresh_aggregate_status(asset)
            await session.commit()
        await _notify_asset_status_changed(asset_id)

    except Exception as exc:
        logger.exception("download_failed asset_id=%s url=%s", asset_id, url)
        async with SessionLocal() as session:
            asset = await session.get(Asset, asset_id)
            if asset is not None:
                asset.download_status = "failed"
                asset.status = "failed"
                await session.commit()
        await _notify_asset_status_changed(asset_id)
        raise

    # Chain into fingerprinting with the downloaded file path.
    # Queue, don't await — ingest_asset is its own task and will publish its own events.
    ingest_asset.delay(asset_id=asset_id, video_path=filepath)

    return {"asset_id": asset_id, "video_path": filepath, "download_status": "ready"}