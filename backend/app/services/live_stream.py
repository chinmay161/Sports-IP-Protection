from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse
from uuid import UUID, uuid4

import cv2
import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

try:
    import httpx
except ImportError:  # pragma: no cover - dependency may be absent in lightweight test envs
    class _MissingHTTPError(Exception):
        pass

    class _MissingAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> Any:
            raise LiveStreamError("httpx is required for live stream HLS fetching")

        async def __aexit__(self, *args: Any) -> None:
            return None

    class _MissingHttpx:
        AsyncClient = _MissingAsyncClient
        HTTPError = _MissingHTTPError

    httpx = _MissingHttpx()  # type: ignore[assignment]

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - dependency may be absent in lightweight test envs
    boto3 = None

    class ClientError(Exception):  # type: ignore[no-redef]
        pass

from app.core.config import get_settings
from app.core.redis import redis_client
from app.models.asset import Asset
from app.models.live_stream import LiveSegmentWatermark, LiveStream, LiveViolation
from app.models.match import Match
from app.schemas.fingerprint import FingerprintMatch
from app.schemas.watermark import WatermarkDetection
from app.services.fingerprint import FingerprintService
from app.services.matcher import _compute_severity, _fuse
from app.services.watermark import WatermarkService, decode_watermark_key, lookup_asset_id_by_payload


logger = logging.getLogger(__name__)
settings = get_settings()


class LiveStreamError(Exception):
    pass


@dataclass(slots=True)
class HLSSegment:
    url: str
    sequence: int
    duration_s: float


MOCK_SUSPECT_URLS = [
    "https://piracy-stream-mock-1.example.com/live/feed.m3u8",
    "https://piracy-stream-mock-2.example.com/stream/index.m3u8",
    "https://piracy-stream-mock-3.example.com/hls/match.m3u8",
]

LIVE_TEMP_ROOT = Path(
    os.getenv(
        "SPORTS_IP_LIVE_ROOT",
        str(Path(tempfile.gettempdir()) / "sports-ip") if os.name == "nt" else "/tmp/sports-ip",
    )
)
SUSPECT_URL_KEY = "live:suspect_urls:{stream_id}"


def _aws_client(service_name: str) -> Any:
    if boto3 is None:
        class _MissingBotoClient:
            def __getattr__(self, name: str) -> Any:
                raise LiveStreamError("boto3 and botocore are required for live stream AWS operations")

        return _MissingBotoClient()
    kwargs: dict[str, Any] = {"region_name": settings.aws_region}
    kwargs["aws_access_key_id"] = settings.aws_access_key_id or "unused"
    kwargs["aws_secret_access_key"] = settings.aws_secret_access_key or "unused"
    return boto3.client(service_name, **kwargs)


s3 = _aws_client("s3")
cf = _aws_client("cloudfront")


def suspect_url_key(stream_id: str | UUID) -> str:
    return SUSPECT_URL_KEY.format(stream_id=str(stream_id))


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _run_blocking(func: Any, *args: Any, **kwargs: Any) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


def _temp_dir() -> Path:
    return LIVE_TEMP_ROOT / f"live_{uuid4()}"


def _mock_segments(manifest_url: str, max_segments: int = 5) -> list[HLSSegment]:
    fixture = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "sample_clip.mp4"
    base = fixture.as_uri()
    return [
        HLSSegment(url=f"{base}?mock_manifest={i}", sequence=i, duration_s=4.0)
        for i in range(max_segments)
    ]


def _is_segment_line(line: str) -> bool:
    cleaned = line.strip()
    path = cleaned.split("?", 1)[0].lower()
    return path.endswith(".ts") or path.endswith(".m3u8")


def _parse_media_manifest(text: str, manifest_url: str, max_segments: int) -> list[HLSSegment]:
    sequence = 0
    current_duration = 0.0
    offset = 0
    segments: list[HLSSegment] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
            try:
                sequence = int(line.split(":", 1)[1])
            except ValueError as exc:
                raise LiveStreamError("Malformed EXT-X-MEDIA-SEQUENCE") from exc
        elif line.startswith("#EXTINF:"):
            value = line.split(":", 1)[1].split(",", 1)[0]
            try:
                current_duration = float(value)
            except ValueError as exc:
                raise LiveStreamError("Malformed EXTINF duration") from exc
        elif not line.startswith("#") and _is_segment_line(line):
            segments.append(
                HLSSegment(
                    url=urljoin(manifest_url, line),
                    sequence=sequence + offset,
                    duration_s=current_duration,
                )
            )
            offset += 1
            current_duration = 0.0

    if not segments:
        raise LiveStreamError("Malformed HLS manifest: no segments")
    return segments[-max_segments:]


def _highest_bandwidth_variant(text: str, manifest_url: str) -> str | None:
    best_bandwidth = -1
    best_url: str | None = None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if not line.startswith("#EXT-X-STREAM-INF"):
            continue
        match = re.search(r"BANDWIDTH=(\d+)", line)
        if match is None or index + 1 >= len(lines):
            continue
        candidate = lines[index + 1]
        if candidate.startswith("#"):
            continue
        bandwidth = int(match.group(1))
        if bandwidth > best_bandwidth:
            best_bandwidth = bandwidth
            best_url = urljoin(manifest_url, candidate)
    return best_url


def _extract_first_iframe(ts_bytes: bytes) -> bytes:
    result = subprocess.run(
        ["ffmpeg", "-i", "pipe:0", "-vframes", "1", "-q:v", "2", "-f", "image2", "pipe:1"],
        input=ts_bytes,
        capture_output=True,
    )
    if result.returncode != 0 and not result.stdout:
        return b""
    return result.stdout


def _render_segment_with_frame(ts_bytes: bytes, frame_path: Path) -> bytes:
    result = subprocess.run(
        [
            "ffmpeg",
            "-i",
            "pipe:0",
            "-loop",
            "1",
            "-i",
            str(frame_path),
            "-filter_complex",
            "[0:v][1:v]overlay=0:0:shortest=1",
            "-c:v",
            "libx264",
            "-c:a",
            "copy",
            "-f",
            "mpegts",
            "pipe:1",
        ],
        input=ts_bytes,
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip().splitlines()
        raise LiveStreamError(stderr[-1] if stderr else f"ffmpeg exited {result.returncode}")
    return result.stdout


async def _fingerprint_match(segment_path: str, asset_id: UUID | None = None) -> list[FingerprintMatch]:
    service = FingerprintService()
    call = service.match
    kwargs: dict[str, Any] = {"threshold": 12}
    if asset_id is not None and "asset_ids" in inspect.signature(call).parameters:
        kwargs["asset_ids"] = [asset_id]
    if inspect.iscoroutinefunction(call):
        return await call(segment_path, **kwargs)
    return await _run_blocking(call, segment_path, **kwargs)


async def _download_segment(client: httpx.AsyncClient, segment: HLSSegment, dest: Path) -> Path:
    if segment.url.startswith("file://"):
        parsed = urlparse(segment.url)
        source_path = unquote(parsed.path)
        if parsed.netloc:
            source_path = f"//{parsed.netloc}{source_path}"
        if os.name == "nt" and re.match(r"^/[A-Za-z]:/", source_path):
            source_path = source_path[1:]
        source = Path(source_path)
        await _run_blocking(shutil.copyfile, source, dest)
        return dest
    response = await client.get(segment.url)
    response.raise_for_status()
    dest.write_bytes(response.content)
    return dest


async def fetch_hls_segments(manifest_url: str, max_segments: int = 5) -> list[HLSSegment]:
    if ("mock" in manifest_url or manifest_url in MOCK_SUSPECT_URLS) and not settings.allow_real_cdn_requests:
        return _mock_segments(manifest_url, max_segments=max_segments)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(manifest_url)
            response.raise_for_status()
            variant_url = _highest_bandwidth_variant(response.text, manifest_url)
            if variant_url is not None:
                response = await client.get(variant_url)
                response.raise_for_status()
                manifest_url = variant_url
    except httpx.HTTPError as exc:
        raise LiveStreamError(f"Unable to fetch HLS manifest: {exc}") from exc

    return _parse_media_manifest(response.text, manifest_url, max_segments)


class LiveStreamService:
    @staticmethod
    async def register_stream(
        asset_id: UUID,
        stream_key: str,
        hls_manifest_url: str,
        s3_prefix: str,
        db: AsyncSession,
    ) -> LiveStream:
        stream = LiveStream(
            asset_id=str(asset_id),
            stream_key=stream_key,
            hls_manifest_url=hls_manifest_url,
            s3_prefix=s3_prefix,
            status="active",
        )
        db.add(stream)
        await db.commit()
        await db.refresh(stream)

        key = suspect_url_key(stream.id)
        if await redis_client.scard(key) == 0:
            await redis_client.sadd(key, *MOCK_SUSPECT_URLS)
        await redis_client.publish(
            "stream.registered",
            json.dumps({"stream_id": stream.id, "asset_id": stream.asset_id, "stream_key": stream.stream_key}),
        )
        return stream

    @staticmethod
    async def end_stream(stream_id: UUID, db: AsyncSession) -> None:
        stream = await db.get(LiveStream, str(stream_id))
        if stream is None:
            raise LiveStreamError(f"Live stream {stream_id} not found")
        stream.status = "ended"
        stream.ended_at = _utcnow()
        await db.commit()
        await redis_client.delete(suspect_url_key(stream_id))
        await redis_client.publish(
            "stream.ended",
            json.dumps({"stream_id": str(stream_id), "asset_id": stream.asset_id, "stream_key": stream.stream_key}),
        )

    @staticmethod
    async def watermark_segment(
        stream_id: UUID,
        segment_name: str,
        payload: int,
        db: AsyncSession,
        viewer_token: str | None = None,
    ) -> LiveSegmentWatermark | None:
        stream = await db.get(LiveStream, str(stream_id))
        if stream is None:
            raise LiveStreamError(f"Live stream {stream_id} not found")
        if not settings.live_bucket:
            raise LiveStreamError("LIVE_BUCKET is required")

        s3_key = f"{stream.s3_prefix.rstrip('/')}/{segment_name.lstrip('/')}"
        workspace = _temp_dir()
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            obj = await _run_blocking(lambda: s3.get_object(Bucket=settings.live_bucket, Key=s3_key))
            ts_bytes = obj["Body"].read()

            jpeg_bytes = await _run_blocking(_extract_first_iframe, ts_bytes)
            if not jpeg_bytes:
                logger.info("live_watermark_skipped_no_iframe stream_id=%s segment=%s", stream_id, segment_name)
                return None

            raw = np.frombuffer(jpeg_bytes, dtype=np.uint8)
            bgr_frame = cv2.imdecode(raw, cv2.IMREAD_COLOR)
            if bgr_frame is None:
                logger.info("live_watermark_skipped_no_iframe stream_id=%s segment=%s", stream_id, segment_name)
                return None

            if not settings.watermark_secret_key:
                raise LiveStreamError("WATERMARK_SECRET_KEY is required")
            key = decode_watermark_key(settings.watermark_secret_key)
            rgb_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
            watermarked_rgb = await _run_blocking(WatermarkService.embed, rgb_frame, payload, key, 6)
            watermarked_bgr = cv2.cvtColor(watermarked_rgb, cv2.COLOR_RGB2BGR)
            ok, encoded = cv2.imencode(".jpg", watermarked_bgr)
            if not ok:
                raise LiveStreamError("Unable to encode watermarked frame")

            frame_path = workspace / "watermarked_frame.jpg"
            frame_path.write_bytes(encoded.tobytes())
            watermarked_bytes = await _run_blocking(_render_segment_with_frame, ts_bytes, frame_path)

            await _run_blocking(
                lambda: s3.put_object(
                    Bucket=settings.live_bucket,
                    Key=s3_key,
                    Body=watermarked_bytes,
                    ContentType="video/MP2T",
                )
            )
            if settings.cloudfront_distribution_id:
                await _run_blocking(
                    lambda: cf.create_invalidation(
                        DistributionId=settings.cloudfront_distribution_id,
                        InvalidationBatch={
                            "Paths": {"Quantity": 1, "Items": [f"/{s3_key}"]},
                            "CallerReference": str(uuid4()),
                        },
                    )
                )

            row = LiveSegmentWatermark(
                stream_id=str(stream_id),
                segment_name=segment_name,
                payload=payload,
                viewer_token=viewer_token,
                s3_key=s3_key,
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return row
        finally:
            await _run_blocking(shutil.rmtree, workspace, True)

    @staticmethod
    async def scan_suspect_stream(
        suspect_url: str,
        stream_id: UUID,
        db: AsyncSession,
    ) -> LiveViolation | None:
        stream = await db.get(LiveStream, str(stream_id))
        if stream is None:
            raise LiveStreamError(f"Live stream {stream_id} not found")
        asset = await db.get(Asset, stream.asset_id)
        if asset is None:
            raise LiveStreamError(f"Asset {stream.asset_id} not found")

        workspace = _temp_dir()
        try:
            workspace.mkdir(parents=True, exist_ok=True)
            segments = await fetch_hls_segments(suspect_url, max_segments=settings.inbound_max_segments)
            if not settings.watermark_secret_key:
                raise LiveStreamError("WATERMARK_SECRET_KEY is required")
            key = decode_watermark_key(settings.watermark_secret_key)
            lookup_lock = asyncio.Lock()

            async with httpx.AsyncClient(timeout=10) as client:
                tasks = [
                    LiveStreamService._scan_segment(client, segment, workspace, UUID(stream.asset_id), key, db, lookup_lock)
                    for segment in segments
                ]
                results = await asyncio.gather(*tasks, return_exceptions=True)

            best: tuple[Any, HLSSegment] | None = None
            for result in results:
                if isinstance(result, Exception):
                    logger.warning("live_segment_scan_failed stream_id=%s error=%s", stream_id, result)
                    continue
                fused, segment = result
                if fused is None:
                    continue
                if best is None or fused.confidence > best[0].confidence:
                    best = (fused, segment)

            if best is None or best[0].confidence < 0.55:
                return None

            fused, segment = best
            severity = _compute_severity(fused.confidence, None, fused.match_type)
            violation = LiveViolation(
                stream_id=str(stream_id),
                asset_id=str(fused.asset_id),
                source_url=suspect_url,
                platform="web",
                confidence=fused.confidence,
                match_type=fused.match_type,
                severity=severity,
                watermark_payload=fused.watermark_payload,
                segment_matched=segment.url,
                status="new",
                detected_at=_utcnow(),
            )
            db.add(violation)
            await db.commit()
            await db.refresh(violation)

            if violation.confidence >= 0.7:
                await LiveStreamService.trigger_live_dmca(UUID(violation.id), db)
                await db.refresh(violation)
            return violation
        finally:
            await _run_blocking(shutil.rmtree, workspace, True)

    @staticmethod
    async def _scan_segment(
        client: httpx.AsyncClient,
        segment: HLSSegment,
        workspace: Path,
        stream_asset_id: UUID,
        key: bytes,
        db: AsyncSession,
        lookup_lock: asyncio.Lock,
    ) -> tuple[Any, HLSSegment]:
        path = workspace / f"segment_{segment.sequence}_{uuid4().hex}.ts"
        await _download_segment(client, segment, path)
        jpeg_bytes = await _run_blocking(_extract_first_iframe, path.read_bytes())
        wm_detection: WatermarkDetection | None = None
        if jpeg_bytes:
            frame = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
            if frame is not None:
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                payload, confidence = await _run_blocking(WatermarkService.extract, rgb, key)
                asset_id = None
                if confidence >= 0.5:
                    async with lookup_lock:
                        asset_id = await lookup_asset_id_by_payload(db, payload)
                wm_detection = WatermarkDetection(
                    payload=payload,
                    asset_id=asset_id,
                    confidence=confidence,
                    frames_agreed=1,
                )
        fp_matches = await _fingerprint_match(str(path), stream_asset_id)
        fp_matches = [match for match in fp_matches if match.asset_id == stream_asset_id]
        if wm_detection is not None and wm_detection.asset_id != stream_asset_id:
            wm_detection = None
        return _fuse(fp_matches, wm_detection, None), segment

    @staticmethod
    async def trigger_live_dmca(violation_id: UUID, db: AsyncSession) -> None:
        from app.workers.evidence_task import generate as evidence_generate

        violation = await db.get(LiveViolation, str(violation_id))
        if violation is None:
            raise LiveStreamError(f"Live violation {violation_id} not found")

        match = Match(
            asset_id=violation.asset_id,
            source_url=violation.source_url,
            platform=violation.platform,
            confidence=violation.confidence,
            match_type=violation.match_type,
            severity=violation.severity,
            watermark_payload=violation.watermark_payload,
            view_count=None,
            duration_matched_ms=0,
            status="dmca_sent",
            detected_at=violation.detected_at,
        )
        db.add(match)
        await db.flush()
        violation.status = "dmca_sent"
        violation.dmca_triggered_at = _utcnow()
        await db.commit()
        await db.refresh(match)
        await db.refresh(violation)

        evidence_generate.delay(str(match.id))
        payload = {
            "alert_id": None,
            "match_id": str(match.id),
            "asset_id": violation.asset_id,
            "severity": violation.severity,
            "platform": violation.platform,
            "confidence": round(violation.confidence, 4),
            "detected_at": match.detected_at.isoformat() + "Z",
        }
        await redis_client.publish("match.created", json.dumps(payload))
        logger.critical(
            "live_dmca_triggered stream_id=%s violation_id=%s source_url=%s confidence=%.4f",
            violation.stream_id,
            violation.id,
            violation.source_url,
            violation.confidence,
        )


async def add_suspect_urls(stream_id: UUID, urls: list[str]) -> int:
    key = suspect_url_key(stream_id)
    if urls:
        await redis_client.sadd(key, *urls)
    return int(await redis_client.scard(key))


async def get_suspect_urls(stream_id: UUID) -> list[str]:
    values = await redis_client.smembers(suspect_url_key(stream_id))
    urls = [value.decode("utf-8") if isinstance(value, bytes) else str(value) for value in values]
    return urls or list(MOCK_SUSPECT_URLS)


async def count_violations(db: AsyncSession, stream_id: str) -> int:
    result = await db.execute(select(func.count()).select_from(LiveViolation).where(LiveViolation.stream_id == stream_id))
    return int(result.scalar_one())


def elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
