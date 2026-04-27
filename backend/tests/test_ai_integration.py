from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import verify_token
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.alert import Alert  # noqa: F401
from app.models.asset import Asset
from app.models.evidence import EvidencePackage as EvidencePackageModel  # noqa: F401
from app.models.match import Match
from app.models.watermark import WatermarkRegistry  # noqa: F401
from app.schemas.fingerprint import FingerprintMatch
from app.services.crawler import CandidateVideo


KEY = base64.b64encode(b"matcher-test-key").decode("ascii")


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'ai.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield Session
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def client(session_factory):
    async def override_session():
        async with session_factory() as session:
            yield session

    async def override_token():
        return {"sub": "test"}

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[verify_token] = override_token
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client
    app.dependency_overrides.clear()


def _candidate(view_count: int = 200_000) -> CandidateVideo:
    return CandidateVideo(
        source_url="https://example.test/leak.mp4",
        platform="web",
        channel="example",
        view_count=view_count,
        duration_ms=30_000,
        geo_country="US",
        thumbnail_url=None,
        uploaded_at=datetime.now(UTC),
    )


async def _asset(db: AsyncSession, asset_id: UUID | None = None) -> Asset:
    asset = Asset(
        id=str(asset_id or uuid4()),
        title="Premier League Final",
        description=None,
        status="ready",
        fingerprint_status="ready",
        watermark_status="ready",
        video_path="assets/original.mp4",
    )
    db.add(asset)
    await db.flush()
    return asset


async def _match(db: AsyncSession, asset_id: str, *, status: str = "dmca_sent") -> Match:
    match = Match(
        id=str(uuid4()),
        asset_id=asset_id,
        source_url="https://example.test/infringing.mp4",
        platform="web",
        confidence=0.93,
        match_type="fingerprint",
        severity="critical",
        duration_matched_ms=5000,
        status=status,
        geo_country="US",
        detected_at=datetime(2026, 4, 24, 12, 0, tzinfo=UTC),
    )
    db.add(match)
    await db.flush()
    return match


def test_verify_thumbnail_returns_true_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import matcher

    monkeypatch.setenv("GEMINI_ENABLED", "false")
    matcher.get_settings.cache_clear()
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"image")

    result = asyncio.run(matcher._verify_thumbnail(str(thumb)))

    assert result.is_sports_content is True
    assert result.reason == "AI disabled"


def test_verify_thumbnail_parses_gemini_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import matcher
    from app.core import ai

    monkeypatch.setenv("GEMINI_ENABLED", "true")
    matcher.get_settings.cache_clear()
    ai.get_gemini_flash.cache_clear()
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"image")
    fake_model = SimpleNamespace(
        generate_content=lambda _: SimpleNamespace(
            text='{"is_sports_content":true,"confidence":"high","reason":"stadium"}'
        )
    )
    monkeypatch.setattr(ai, "get_gemini_flash", lambda: fake_model)

    result = asyncio.run(matcher._verify_thumbnail(str(thumb)))

    assert result.is_sports_content is True
    assert result.confidence == "high"
    assert result.reason == "stadium"


def test_verify_thumbnail_downgrades_severity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    session_factory,
) -> None:
    async def run() -> None:
        from app.services import matcher
        from app.services.matcher import MatcherService, VerificationResult

        asset_id = uuid4()
        async with session_factory() as db:
            await _asset(db, asset_id)
            await db.commit()

            async def fake_download(self, url: str, dest: Path) -> Path:
                path = dest / "clip.mp4"
                path.write_bytes(b"clip")
                return path

            async def fake_match(self, video_path: str, threshold: int = 10, asset_ids=None):
                return [FingerprintMatch(asset_id=asset_id, confidence=0.95, start_ms=0, end_ms=5000, match_type="frame")]

            async def fake_detect(self, url: str, key: bytes):
                return None

            async def fake_verify(path: str):
                return VerificationResult(False, "not sports", "high", "")

            def fake_extract(video_path: Path, ms: int, out_path: Path) -> None:
                out_path.write_bytes(b"jpg")

            async def fake_publish(channel: str, message: str):
                return 1

            monkeypatch.setenv("WATERMARK_SECRET_KEY", KEY)
            monkeypatch.setenv("SPORTS_IP_SCAN_ROOT", str(tmp_path / "scan-root"))
            matcher.get_settings.cache_clear()
            monkeypatch.setattr(matcher.CrawlerService, "download_clip", fake_download)
            monkeypatch.setattr(matcher.FingerprintService, "match", fake_match)
            monkeypatch.setattr(matcher.WatermarkService, "detect_from_url", fake_detect)
            monkeypatch.setattr(matcher, "_verify_thumbnail", fake_verify)
            monkeypatch.setattr(matcher, "_extract_frame", fake_extract)
            monkeypatch.setattr(matcher.redis_client, "publish", fake_publish)

            result = await MatcherService.scan(_candidate(), [asset_id], db)
            assert result is not None
            db_match = await db.get(Match, result.id)
            assert db_match.severity == "high"
            assert db_match.gemini_is_sports_content is False

    asyncio.run(run())


def test_verify_thumbnail_fallback_on_exception(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import matcher
    from app.core import ai

    monkeypatch.setenv("GEMINI_ENABLED", "true")
    matcher.get_settings.cache_clear()
    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"image")
    fake_model = SimpleNamespace(generate_content=lambda _: (_ for _ in ()).throw(Exception("API error")))
    monkeypatch.setattr(ai, "get_gemini_flash", lambda: fake_model)

    result = asyncio.run(matcher._verify_thumbnail(str(thumb)))

    assert result.is_sports_content is True
    assert "verification failed" in result.reason


def test_generate_summary_returns_fallback_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import evidence

    monkeypatch.setenv("GEMINI_ENABLED", "false")
    evidence.get_settings.cache_clear()

    result = asyncio.run(evidence._generate_incident_summary({}))

    assert result == evidence.STATIC_INCIDENT_SUMMARY


def test_generate_summary_length_validated(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    from app.services import evidence
    from app.core import ai

    monkeypatch.setenv("GEMINI_ENABLED", "true")
    evidence.get_settings.cache_clear()
    monkeypatch.setattr(ai, "get_gemini_pro", lambda: SimpleNamespace(generate_content=lambda _: SimpleNamespace(text="short")))

    result = asyncio.run(evidence._generate_incident_summary({}))

    assert result == evidence.STATIC_INCIDENT_SUMMARY
    assert "invalid_length" in caplog.text


@pytest.mark.asyncio
async def test_generate_summary_in_pdf(
    session_factory,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.services import evidence
    from app.services.evidence import EvidenceService

    uploads: dict[str, bytes] = {}

    def upload_file(local_path, s3_key: str) -> None:
        uploads[s3_key] = Path(local_path).read_bytes()

    def extract_thumbnail(match: Match, segment, local_path: Path) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(b"fake-image")

    monkeypatch.setattr(evidence.storage, "upload_file", upload_file)
    monkeypatch.setattr(evidence, "_extract_thumbnail", extract_thumbnail)
    monkeypatch.setattr(evidence, "_generate_incident_summary", lambda manifest: asyncio.sleep(0, "Test summary paragraph. " * 6))

    async with session_factory() as db:
        asset = await _asset(db)
        match = await _match(db, asset.id)
        from app.models.match import MatchSegment

        db.add(
            MatchSegment(
                match_id=match.id,
                asset_start_ms=0,
                asset_end_ms=1000,
                source_start_ms=0,
                source_end_ms=1000,
                frame_run_length=1,
            )
        )
        await db.commit()

        package = await EvidenceService().generate(match.id, db)

    assert uploads[package.pdf_s3_key].startswith(b"%PDF")


def test_generate_summary_fallback_on_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import evidence
    from app.core import ai

    monkeypatch.setenv("GEMINI_ENABLED", "true")
    evidence.get_settings.cache_clear()
    monkeypatch.setattr(ai, "get_gemini_pro", lambda: SimpleNamespace(generate_content=lambda _: (_ for _ in ()).throw(Exception("boom"))))

    result = asyncio.run(evidence._generate_incident_summary({}))

    assert result == evidence.STATIC_INCIDENT_SUMMARY


def test_detect_shots_returns_empty_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import fingerprint

    monkeypatch.setenv("VIDEO_INTELLIGENCE_ENABLED", "false")
    fingerprint.get_settings.cache_clear()

    assert asyncio.run(fingerprint._detect_shots("missing.mp4")) == []


def test_generate_falls_back_to_1fps_when_shots_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import fingerprint
    from app.services.fingerprint import FingerprintService, FingerprintVector
    from tests.test_fingerprint import FakeCollection

    service = FingerprintService(collection=FakeCollection())
    service.settings.temp_root = tmp_path

    monkeypatch.setattr(fingerprint, "_detect_shots", lambda _: asyncio.sleep(0, []))
    monkeypatch.setattr(service, "_probe_duration_ms", lambda _: asyncio.sleep(0, 2000))

    async def fake_extract_frames(_: str, frames_dir: Path, timestamps_ms=None):
        assert timestamps_ms == [0, 1000]
        paths = [frames_dir / "frame_000000.jpg", frames_dir / "frame_000001.jpg"]
        for path in paths:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"frame")
        return paths

    monkeypatch.setattr(service, "_extract_frames", fake_extract_frames)
    monkeypatch.setattr(service, "_hash_frames", lambda paths: asyncio.sleep(0, [FingerprintVector(index * 1000, b"\x01" * 8, "frame") for index, _ in enumerate(paths)]))
    monkeypatch.setattr(service, "_has_audio_stream", lambda _: asyncio.sleep(0, False))

    result = asyncio.run(service.generate("clip.mp4", uuid4()))

    assert result.frame_count > 0


def test_detect_shots_fallback_on_exception(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    from app.services import fingerprint

    monkeypatch.setenv("VIDEO_INTELLIGENCE_ENABLED", "true")
    fingerprint.get_settings.cache_clear()

    result = asyncio.run(fingerprint._detect_shots("missing.mp4"))

    assert result == []
    assert "shot_detection_failed" in caplog.text


def test_fuzzy_score_exact_match() -> None:
    from app.services.lookalike import _fuzzy_score

    assert _fuzzy_score("Premier League", "Premier League") == 1.0


def test_fuzzy_score_different_strings() -> None:
    from app.services.lookalike import _fuzzy_score

    assert _fuzzy_score("RandomChannel", "UEFA Champions League") < 0.4


def test_check_early_return_low_score() -> None:
    from app.services import lookalike

    result = asyncio.run(lookalike.check("XYZ Random Channel 99"))

    assert result.is_impersonator is False
    assert result.matched_brand is None


def test_gemini_catches_unicode_substitution(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import lookalike

    monkeypatch.setattr(lookalike, "_gemini_impersonation_check", lambda channel, brand: asyncio.sleep(0, (True, "unicode trick")))

    result = asyncio.run(lookalike.check("Premier LeagIe"))

    assert result.is_impersonator is True
    assert result.confidence >= 0.6


def test_check_disabled_gemini_uses_fuzzy_only(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import lookalike

    monkeypatch.setenv("GEMINI_ENABLED", "false")
    lookalike.get_settings.cache_clear()

    result = asyncio.run(lookalike.check("Premier League HD"))

    assert result.is_impersonator is False
    assert result.confidence < 0.6


def test_check_batch_runs_concurrently() -> None:
    from app.services.lookalike import check_batch

    results = asyncio.run(check_batch(["Premier League HD", "Random", "ESPN Live"]))

    assert len(results) == 3


@pytest.mark.asyncio
async def test_lookalike_endpoint_validates_max_50(client) -> None:
    response = await client.post("/detections/lookalike-check", json={"channel_names": [f"name-{i}" for i in range(51)]})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_lookalike_endpoint_returns_results(client, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api import detections
    from app.services.lookalike import LookalikeResult

    async def fake_check_batch(names: list[str]):
        return [
            LookalikeResult(name, False, None, 0.1, None, None, 0.0)
            for name in names
        ]

    monkeypatch.setattr(detections.lookalike, "check_batch", fake_check_batch)

    response = await client.post("/detections/lookalike-check", json={"channel_names": ["a", "b"]})

    assert response.status_code == 200
    assert len(response.json()) == 2
