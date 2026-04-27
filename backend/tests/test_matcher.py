import asyncio
import base64
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.alert import Alert  # noqa: F401
from app.models.asset import Asset
from app.models.match import Match, MatchSegment
from app.models.watermark import WatermarkRegistry  # noqa: F401
from app.schemas.fingerprint import FingerprintMatch
from app.schemas.watermark import WatermarkDetection
from app.services.crawler import CandidateVideo
from app.services.matcher import MatcherService, _compute_severity, _fuse


KEY = base64.b64encode(b"matcher-test-key").decode("ascii")


def _fp(asset_id: UUID, confidence: float = 0.8) -> FingerprintMatch:
    return FingerprintMatch(
        asset_id=asset_id,
        confidence=confidence,
        start_ms=0,
        end_ms=5000,
        match_type="frame",
    )


def _wm(asset_id: UUID, confidence: float = 0.85) -> WatermarkDetection:
    return WatermarkDetection(
        payload=123,
        asset_id=asset_id,
        confidence=confidence,
        frames_agreed=4,
    )


def _candidate() -> CandidateVideo:
    return CandidateVideo(
        source_url="https://example.test/leak.mp4",
        platform="web",
        channel="example",
        view_count=1500,
        duration_ms=30_000,
        geo_country="US",
        thumbnail_url=None,
        uploaded_at=datetime.now(UTC),
    )


async def _make_db(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'matcher.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    return engine, Session


async def _insert_asset(db, asset_id: UUID) -> None:
    db.add(
        Asset(
            id=str(asset_id),
            title="Test Match",
            status="ready",
            fingerprint_status="ready",
            watermark_status="ready",
            video_path="clip.mp4",
        )
    )
    await db.commit()


def test_fuse_both_match() -> None:
    asset_id = uuid4()
    fused = _fuse([_fp(asset_id, 0.80)], _wm(asset_id, 0.85), 5_000)

    assert fused is not None
    assert fused.confidence == min(1.0, 0.80 * 1.25)
    assert fused.match_type == "both"


def test_fuse_watermark_only() -> None:
    asset_id = uuid4()
    fused = _fuse([], _wm(asset_id, 0.75), 5_000)

    assert fused is not None
    assert fused.confidence == pytest.approx(0.75 * 0.85)
    assert fused.match_type == "watermark"


def test_fuse_fingerprint_only() -> None:
    asset_id = uuid4()
    fused = _fuse([_fp(asset_id, 0.78)], None, 500)

    assert fused is not None
    assert fused.confidence == 0.78
    assert fused.match_type == "fingerprint"


def test_fuse_below_floor_returns_none() -> None:
    assert _fuse([_fp(uuid4(), 0.40)], None, 500) is None


def test_fuse_no_input_returns_none() -> None:
    assert _fuse([], None, 500) is None


def test_severity_critical_both_type() -> None:
    assert _compute_severity(0.70, 5_000, "both") == "critical"


def test_severity_critical_high_views() -> None:
    assert _compute_severity(0.92, 200_000, "fingerprint") == "critical"


def test_severity_high() -> None:
    assert _compute_severity(0.85, 15_000, "fingerprint") == "high"


def test_severity_medium() -> None:
    assert _compute_severity(0.70, 500, "fingerprint") == "medium"


def test_severity_low() -> None:
    assert _compute_severity(0.55, None, "fingerprint") == "low"


def test_scan_returns_none_when_no_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        from app.services import matcher

        asset_id = uuid4()
        engine, Session = await _make_db(tmp_path)
        async with Session() as db:
            await _insert_asset(db, asset_id)

            async def fake_download(self, url: str, dest: Path) -> Path:
                path = dest / "clip.mp4"
                path.write_bytes(b"clip")
                return path

            async def fake_match(self, video_path: str, threshold: int = 10):
                return []

            async def fake_detect(self, url: str, key: bytes):
                return None

            monkeypatch.setenv("WATERMARK_SECRET_KEY", KEY)
            monkeypatch.setenv("SPORTS_IP_SCAN_ROOT", str(tmp_path / "scan-root"))
            matcher.get_settings.cache_clear()
            monkeypatch.setattr(matcher.CrawlerService, "download_clip", fake_download)
            monkeypatch.setattr(matcher.FingerprintService, "match", fake_match)
            monkeypatch.setattr(matcher.WatermarkService, "detect_from_url", fake_detect)

            assert await MatcherService.scan(_candidate(), [asset_id], db) is None
            rows = await db.execute(select(Match))
            assert rows.scalars().all() == []
        await engine.dispose()

    asyncio.run(run())


def test_scan_inserts_match_and_segments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        from app.services import matcher

        asset_id = uuid4()
        engine, Session = await _make_db(tmp_path)
        async with Session() as db:
            await _insert_asset(db, asset_id)

            async def fake_download(self, url: str, dest: Path) -> Path:
                path = dest / "clip.mp4"
                path.write_bytes(b"clip")
                return path

            async def fake_match(self, video_path: str, threshold: int = 10):
                return [_fp(asset_id, 0.85)]

            async def fake_detect(self, url: str, key: bytes):
                return None

            async def fake_publish(channel: str, message: str):
                return 1

            monkeypatch.setenv("WATERMARK_SECRET_KEY", KEY)
            monkeypatch.setenv("SPORTS_IP_SCAN_ROOT", str(tmp_path / "scan-root"))
            matcher.get_settings.cache_clear()
            monkeypatch.setattr(matcher.CrawlerService, "download_clip", fake_download)
            monkeypatch.setattr(matcher.FingerprintService, "match", fake_match)
            monkeypatch.setattr(matcher.WatermarkService, "detect_from_url", fake_detect)
            monkeypatch.setattr(matcher.redis_client, "publish", fake_publish)

            result = await MatcherService.scan(_candidate(), [asset_id], db)
            assert result is not None
            assert result.confidence == 0.85
            assert result.match_type == "fingerprint"
            db_match = await db.get(Match, result.id)
            assert db_match is not None
            segments = await db.execute(select(MatchSegment).where(MatchSegment.match_id == result.id))
            assert len(segments.scalars().all()) == 1
        await engine.dispose()

    asyncio.run(run())


def test_scan_publishes_redis_event(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        from app.services import matcher

        asset_id = uuid4()
        published: list[tuple[str, str]] = []
        engine, Session = await _make_db(tmp_path)
        async with Session() as db:
            await _insert_asset(db, asset_id)

            async def fake_download(self, url: str, dest: Path) -> Path:
                path = dest / "clip.mp4"
                path.write_bytes(b"clip")
                return path

            async def fake_match(self, video_path: str, threshold: int = 10):
                return [_fp(asset_id, 0.85)]

            async def fake_detect(self, url: str, key: bytes):
                return None

            async def fake_publish(channel: str, message: str):
                published.append((channel, message))
                return 1

            monkeypatch.setenv("WATERMARK_SECRET_KEY", KEY)
            monkeypatch.setenv("SPORTS_IP_SCAN_ROOT", str(tmp_path / "scan-root"))
            matcher.get_settings.cache_clear()
            monkeypatch.setattr(matcher.CrawlerService, "download_clip", fake_download)
            monkeypatch.setattr(matcher.FingerprintService, "match", fake_match)
            monkeypatch.setattr(matcher.WatermarkService, "detect_from_url", fake_detect)
            monkeypatch.setattr(matcher.redis_client, "publish", fake_publish)

            result = await MatcherService.scan(_candidate(), [asset_id], db)
            assert result is not None
            assert len(published) == 1
            channel, raw = published[0]
            payload = json.loads(raw)
            assert channel == "match.created"
            assert payload["alert_id"]
            assert payload["match_id"] == str(result.id)
            assert payload["severity"] == "medium"
            assert payload["platform"] == "web"
            assert payload["confidence"] == 0.85
            alert = await db.get(Alert, payload["alert_id"])
            assert alert is not None
            assert alert.asset_id == str(asset_id)
            assert alert.infringing_url == result.source_url
        await engine.dispose()

    asyncio.run(run())


def test_scan_keeps_fingerprint_match_when_watermark_detection_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        from app.services import matcher

        asset_id = uuid4()
        engine, Session = await _make_db(tmp_path)
        async with Session() as db:
            await _insert_asset(db, asset_id)

            async def fake_download(self, url: str, dest: Path) -> Path:
                path = dest / "clip.mp4"
                path.write_bytes(b"clip")
                return path

            async def fake_match(self, video_path: str, threshold: int = 10):
                return [_fp(asset_id, 0.85)]

            async def fake_detect(self, url: str, key: bytes):
                raise RuntimeError("ffmpeg error (see stderr output for detail)")

            async def fake_publish(channel: str, message: str):
                return 1

            monkeypatch.setenv("WATERMARK_SECRET_KEY", KEY)
            monkeypatch.setenv("SPORTS_IP_SCAN_ROOT", str(tmp_path / "scan-root"))
            matcher.get_settings.cache_clear()
            monkeypatch.setattr(matcher.CrawlerService, "download_clip", fake_download)
            monkeypatch.setattr(matcher.FingerprintService, "match", fake_match)
            monkeypatch.setattr(matcher.WatermarkService, "detect_from_url", fake_detect)
            monkeypatch.setattr(matcher.redis_client, "publish", fake_publish)

            result = await MatcherService.scan(_candidate(), [asset_id], db)

            assert result is not None
            assert result.match_type == "fingerprint"
            assert result.confidence == 0.85
        await engine.dispose()

    asyncio.run(run())


def test_scan_cleans_up_tmp_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        from app.services import matcher

        asset_id = uuid4()
        scan_id = UUID("00000000-0000-0000-0000-000000000001")
        engine, Session = await _make_db(tmp_path)
        async with Session() as db:
            await _insert_asset(db, asset_id)

            async def fake_download(self, url: str, dest: Path) -> Path:
                path = dest / "clip.mp4"
                path.write_bytes(b"clip")
                return path

            async def fake_match(self, video_path: str, threshold: int = 10):
                return []

            async def fake_detect(self, url: str, key: bytes):
                return None

            ids = iter([scan_id])
            monkeypatch.setenv("WATERMARK_SECRET_KEY", KEY)
            monkeypatch.setenv("SPORTS_IP_SCAN_ROOT", str(tmp_path / "scan-root"))
            matcher.get_settings.cache_clear()
            monkeypatch.setattr(matcher, "uuid4", lambda: next(ids))
            monkeypatch.setattr(matcher.CrawlerService, "download_clip", fake_download)
            monkeypatch.setattr(matcher.FingerprintService, "match", fake_match)
            monkeypatch.setattr(matcher.WatermarkService, "detect_from_url", fake_detect)

            await MatcherService.scan(_candidate(), [asset_id], db)
            assert not (tmp_path / "scan-root" / f"scan_{scan_id}").exists()
        await engine.dispose()

    asyncio.run(run())


def test_scan_all_skips_exceptions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        from app.services import matcher

        asset_id = uuid4()
        engine, Session = await _make_db(tmp_path)
        async with Session() as db:
            await _insert_asset(db, asset_id)
            candidates = [_candidate() for _ in range(5)]
            candidates = [
                CandidateVideo(
                    source_url=f"https://example.test/{index}.mp4",
                    platform=item.platform,
                    channel=item.channel,
                    view_count=item.view_count,
                    duration_ms=item.duration_ms,
                    geo_country=item.geo_country,
                    thumbnail_url=item.thumbnail_url,
                    uploaded_at=item.uploaded_at,
                )
                for index, item in enumerate(candidates)
            ]
            match = Match(
                id=str(uuid4()),
                asset_id=str(asset_id),
                source_url="https://example.test/match.mp4",
                platform="web",
                confidence=0.8,
                match_type="fingerprint",
                severity="medium",
                duration_matched_ms=5000,
                status="new",
            )

            async def fake_crawl_all(self, query: str, max_per_platform: int):
                return candidates

            async def fake_scan(candidate, asset_ids, db):
                if candidate.source_url.endswith(("0.mp4", "1.mp4")):
                    raise RuntimeError("scan failed")
                return match

            monkeypatch.setattr(matcher.CrawlerService, "crawl_all", fake_crawl_all)
            monkeypatch.setattr(matcher.MatcherService, "scan", fake_scan)

            results = await MatcherService.scan_all(asset_id, db)
            assert results == [match, match, match]
        await engine.dispose()

    asyncio.run(run())
