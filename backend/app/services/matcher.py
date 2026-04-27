import asyncio
import inspect
import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import redis_client
from app.models.alert import Alert
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
    gemini_verification_reason: str | None = None
    gemini_is_sports_content: bool | None = None


@dataclass(slots=True)
class VerificationResult:
    is_sports_content: bool
    reason: str
    confidence: str
    raw_response: str


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


def _truncate(value: str, max_length: int = 100) -> str:
    return value if len(value) <= max_length else value[: max_length - 3] + "..."


def _strip_json_fences(text: str) -> str:
    cleaned = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, flags=re.IGNORECASE | re.DOTALL)
    return fenced.group(1).strip() if fenced else cleaned


def _extract_frame(video_path: Path, ms: int, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{ms / 1000:.3f}",
            "-i",
            str(video_path),
            "-vframes",
            "1",
            "-q:v",
            "2",
            str(out_path),
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode(errors="replace").strip().splitlines()
        raise RuntimeError(stderr[-1] if stderr else f"ffmpeg exited {result.returncode}")


async def _verify_thumbnail(thumbnail_path: str) -> VerificationResult:
    settings = get_settings()
    if not settings.gemini_enabled:
        return VerificationResult(True, "AI disabled", "low", "")

    prompt = """You are a sports media content verifier.
Analyse this image and determine if it contains sports broadcast
footage, match highlights, stadium scenes, or sports media content.

Reply in this exact JSON format with no other text:
{
  "is_sports_content": true or false,
  "confidence": "high" or "medium" or "low",
  "reason": "one sentence explanation"
}
"""
    try:
        thumbnail_bytes = Path(thumbnail_path).read_bytes()
        image_part = {"mime_type": "image/jpeg", "data": thumbnail_bytes}

        from app.core.ai import get_gemini_flash

        gemini_flash = get_gemini_flash()
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: gemini_flash.generate_content([prompt, image_part]),
        )
        raw_response = (getattr(response, "text", None) or "").strip()
        payload = json.loads(_strip_json_fences(raw_response))
        confidence = str(payload.get("confidence", "low")).lower()
        if confidence not in {"high", "medium", "low"}:
            confidence = "low"
        return VerificationResult(
            is_sports_content=bool(payload.get("is_sports_content", True)),
            reason=str(payload.get("reason", ""))[:500],
            confidence=confidence,
            raw_response=raw_response,
        )
    except Exception as exc:
        logger.warning(
            "gemini_thumbnail_verification_failed path=%s error=%s",
            thumbnail_path,
            _truncate(str(exc)),
        )
        return VerificationResult(True, f"verification failed: {exc}", "low", "")


async def _fingerprint_match(video_path: str, asset_ids: list[UUID] | None = None) -> list[FingerprintMatch]:
    service = FingerprintService()
    call = service.match
    kwargs = {"threshold": 10}
    if "asset_ids" in inspect.signature(call).parameters:
        kwargs["asset_ids"] = asset_ids
    if inspect.iscoroutinefunction(call):
        return await call(video_path, **kwargs)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: call(video_path, **kwargs))


async def _watermark_detect(video_path: str, key: bytes) -> WatermarkDetection | None:
    try:
        return await WatermarkService().detect_from_url(video_path, key)
    except Exception as exc:
        logger.warning("watermark_detection_failed path=%s error=%s", video_path, exc)
        return None


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

            fp_task = _fingerprint_match(str(video_path), asset_ids)
            wm_task = _watermark_detect(str(video_path), key)
            fp_matches, wm_detection = await asyncio.gather(fp_task, wm_task)
            allowed_assets = set(asset_ids)
            fp_matches = [match for match in fp_matches if match.asset_id in allowed_assets]
            if wm_detection is not None and wm_detection.asset_id not in allowed_assets:
                wm_detection = None

            fused = _fuse(fp_matches, wm_detection, candidate.view_count)
            if fused is None:
                return None

            if fused.severity in ("high", "critical") and fused.fp_matches:
                segment = fused.fp_matches[0]
                midpoint_ms = (segment.start_ms + segment.end_ms) // 2
                thumb_path = dest / "verify_thumb.jpg"
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, lambda: _extract_frame(Path(video_path), midpoint_ms, thumb_path))
                    verification = await _verify_thumbnail(str(thumb_path))
                except Exception as exc:
                    logger.warning(
                        "gemini_thumbnail_extract_failed asset=%s error=%s",
                        fused.asset_id,
                        _truncate(str(exc)),
                    )
                    verification = VerificationResult(True, f"verification failed: {exc}", "low", "")
                if not verification.is_sports_content:
                    severity_order = ["low", "medium", "high", "critical"]
                    current_idx = severity_order.index(fused.severity)
                    fused.severity = severity_order[max(0, current_idx - 1)]
                    logger.info(
                        "gemini_severity_downgraded asset=%s reason=%s",
                        fused.asset_id,
                        _truncate(verification.reason),
                    )
                fused.gemini_verification_reason = verification.reason
                fused.gemini_is_sports_content = verification.is_sports_content

            alert_id = str(uuid4())
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
                    gemini_verification_reason=fused.gemini_verification_reason,
                    gemini_is_sports_content=fused.gemini_is_sports_content,
                )
                db.add(match)
                await db.flush()

                alert = Alert(
                    id=alert_id,
                    asset_id=str(fused.asset_id),
                    status="open",
                    severity_score=fused.confidence,
                    severity_label=fused.severity,
                    match_type=fused.match_type,
                    confidence=fused.confidence,
                    infringing_url=candidate.source_url,
                    platform=candidate.platform,
                    ai_reasoning="Generated from automated match scan.",
                    notified_email=False,
                )
                db.add(alert)

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
                "alert_id": alert_id,
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

        crawler = CrawlerService()
        crawl_all = crawler.crawl_all
        if "asset_id" in inspect.signature(crawl_all).parameters:
            candidates = await crawl_all(asset_title, max_per_platform, asset_id=asset_id)
        else:
            candidates = await crawl_all(asset_title, max_per_platform)
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
