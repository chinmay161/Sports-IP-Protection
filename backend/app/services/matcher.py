import asyncio
import inspect
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import redis_client
from app.models.asset import Asset
from app.models.match import Match, MatchSegment
from app.schemas.fingerprint import FingerprintMatch
from app.schemas.watermark import WatermarkDetection
from app.services.crawler import CandidateVideo, CrawlerService
from app.services.fingerprint import FingerprintService
from app.services.watermark import WatermarkService, decode_watermark_key


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class FusedResult:
    asset_id: UUID
    confidence: float
    match_type: str
    severity: str
    watermark_payload: int | None
    fp_matches: list[FingerprintMatch]


def _compute_severity(confidence: float, view_count: int | None, match_type: str) -> str:
    views = view_count or 0
    if (confidence >= 0.9 and views >= 100_000) or match_type == "both":
        return "critical"
    if confidence >= 0.8 and views >= 10_000:
        return "high"
    if confidence >= 0.65:
        return "medium"
    return "low"


def _fuse(
    fp_matches: list[FingerprintMatch],
    wm_detection: WatermarkDetection | None,
    view_count: int | None,
) -> FusedResult | None:
    if not fp_matches and wm_detection is None:
        return None

    asset_id: UUID | None
    confidence: float
    match_type: str
    watermark_payload: int | None = None
    fused_fp_matches: list[FingerprintMatch]

    if wm_detection is not None and wm_detection.asset_id is not None:
        matching_fp = [match for match in fp_matches if match.asset_id == wm_detection.asset_id]
        watermark_payload = wm_detection.payload
        if matching_fp:
            asset_id = wm_detection.asset_id
            confidence = min(1.0, max(match.confidence for match in matching_fp) * 1.25)
            match_type = "both"
            fused_fp_matches = matching_fp
        else:
            asset_id = wm_detection.asset_id
            confidence = wm_detection.confidence * 0.85
            match_type = "watermark"
            fused_fp_matches = []
    elif wm_detection is not None:
        return None
    else:
        best_fp = max(fp_matches, key=lambda match: match.confidence)
        asset_id = best_fp.asset_id
        confidence = best_fp.confidence
        match_type = "fingerprint"
        fused_fp_matches = [match for match in fp_matches if match.asset_id == asset_id]

    if confidence < 0.5:
        return None

    severity = _compute_severity(confidence, view_count, match_type)
    return FusedResult(
        asset_id=asset_id,
        confidence=confidence,
        match_type=match_type,
        severity=severity,
        watermark_payload=watermark_payload,
        fp_matches=fused_fp_matches,
    )


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _scan_dest() -> Path:
    root = os.getenv("SPORTS_IP_SCAN_ROOT", "/tmp/sports-ip")
    return Path(root) / f"scan_{uuid4()}"


async def _fingerprint_match(video_path: str) -> list[FingerprintMatch]:
    service = FingerprintService()
    call = service.match
    if inspect.iscoroutinefunction(call):
        return await call(video_path, threshold=10)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: call(video_path, threshold=10))


class MatcherService:
    @staticmethod
    async def scan(candidate: CandidateVideo, asset_ids: list[UUID], db: AsyncSession) -> Match | None:
        dest = _scan_dest()
        try:
            dest.mkdir(parents=True, exist_ok=True)
            video_path = await CrawlerService().download_clip(candidate.source_url, dest)

            settings = get_settings()
            if not settings.watermark_secret_key:
                raise RuntimeError("WATERMARK_SECRET_KEY is required")
            key = decode_watermark_key(settings.watermark_secret_key)

            fp_task = _fingerprint_match(str(video_path))
            wm_task = WatermarkService().detect_from_url(candidate.source_url, key)
            fp_matches, wm_detection = await asyncio.gather(fp_task, wm_task)
            allowed_assets = set(asset_ids)
            fp_matches = [match for match in fp_matches if match.asset_id in allowed_assets]
            if wm_detection is not None and wm_detection.asset_id not in allowed_assets:
                wm_detection = None

            fused = _fuse(fp_matches, wm_detection, candidate.view_count)
            if fused is None:
                return None

            async with db.begin():
                match = Match(
                    id=str(uuid4()),
                    asset_id=str(fused.asset_id),
                    source_url=candidate.source_url,
                    platform=candidate.platform,
                    confidence=fused.confidence,
                    match_type=fused.match_type,
                    severity=fused.severity,
                    watermark_payload=fused.watermark_payload,
                    source_channel=candidate.channel,
                    view_count=candidate.view_count,
                    duration_matched_ms=sum(
                        fp.end_ms - fp.start_ms for fp in fused.fp_matches
                    ),
                    status="new",
                    geo_country=candidate.geo_country,
                    detected_at=_utcnow(),
                )
                db.add(match)
                await db.flush()

                for fp in fused.fp_matches:
                    segment = MatchSegment(
                        id=str(uuid4()),
                        match_id=match.id,
                        asset_start_ms=fp.start_ms,
                        asset_end_ms=fp.end_ms,
                        source_start_ms=fp.start_ms,
                        source_end_ms=fp.end_ms,
                        frame_run_length=max(1, (fp.end_ms - fp.start_ms) // 1000),
                        audio_confidence=getattr(fp, "audio_confidence", None),
                        thumbnail_s3_key=None,
                    )
                    db.add(segment)

            payload = {
                "match_id": str(match.id),
                "asset_id": str(fused.asset_id),
                "severity": fused.severity,
                "platform": candidate.platform,
                "confidence": round(fused.confidence, 4),
                "detected_at": match.detected_at.isoformat() + "Z",
            }
            await redis_client.publish("match.created", json.dumps(payload))
            return match
        finally:
            shutil.rmtree(dest, ignore_errors=True)

    @staticmethod
    async def scan_all(asset_id: UUID, db: AsyncSession, max_per_platform: int = 20) -> list[Match]:
        start = time.perf_counter()
        asset = await db.get(Asset, str(asset_id))
        if asset is None:
            raise ValueError(f"Asset {asset_id} not found")
        asset_title = asset.title
        await db.rollback()

        candidates = await CrawlerService().crawl_all(asset_title, max_per_platform)
        results = await asyncio.gather(
            *[MatcherService.scan(candidate, [asset_id], db) for candidate in candidates],
            return_exceptions=True,
        )

        matches: list[Match] = []
        for candidate, result in zip(candidates, results, strict=True):
            if isinstance(result, Exception):
                logger.warning("scan_failed url=%s error=%s", candidate.source_url, result)
                continue
            if result is not None:
                matches.append(result)

        elapsed = time.perf_counter() - start
        logger.info(
            "scan_all asset=%s candidates=%d matches=%d elapsed=%.2fs",
            asset_id,
            len(candidates),
            len(matches),
            elapsed,
        )
        return matches
