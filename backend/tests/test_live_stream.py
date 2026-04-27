import base64
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.auth import verify_token
from app.db.base import Base
from app.db.session import get_db_session
from app.models.asset import Asset
from app.models.live_stream import LiveSegmentWatermark, LiveStream, LiveViolation
from app.models.match import Match
from app.models.watermark import WatermarkRegistry
from app.schemas.fingerprint import FingerprintMatch
from app.services import live_stream
from app.services.live_stream import HLSSegment, LiveStreamError, LiveStreamService, MOCK_SUSPECT_URLS


KEY = base64.b64encode(b"live-test-key").decode("ascii")


class FakeRedis:
    def __init__(self) -> None:
        self.sets: dict[str, set[str]] = {}
        self.published: list[tuple[str, str]] = []

    async def scard(self, key: str) -> int:
        return len(self.sets.get(key, set()))

    async def sadd(self, key: str, *values: str) -> int:
        existing = self.sets.setdefault(key, set())
        before = len(existing)
        existing.update(values)
        return len(existing) - before

    async def smembers(self, key: str):
        return set(self.sets.get(key, set()))

    async def delete(self, key: str) -> int:
        return int(self.sets.pop(key, None) is not None)

    async def publish(self, channel: str, payload: str) -> int:
        self.published.append((channel, payload))
        return 1


class FakeResponse:
    def __init__(self, text: str = "", status_code: int = 200, content: bytes = b"") -> None:
        self.text = text
        self.status_code = status_code
        self.content = content

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("failed", request=httpx.Request("GET", "https://x.test"), response=None)


class FakeAsyncClient:
    def __init__(self, responses: dict[str, FakeResponse], seen: list[str] | None = None, **kwargs) -> None:
        self.responses = responses
        self.seen = seen if seen is not None else []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url: str) -> FakeResponse:
        self.seen.append(url)
        return self.responses[url]


async def _make_db(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'live.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    return engine, Session


async def _insert_asset(db, asset_id: UUID) -> None:
    db.add(
        Asset(
            id=str(asset_id),
            title="Live Match",
            status="ready",
            fingerprint_status="ready",
            watermark_status="ready",
            video_path="clip.mp4",
        )
    )
    await db.commit()


async def _insert_stream(db, asset_id: UUID, stream_id: UUID | None = None) -> UUID:
    stream_id = stream_id or uuid4()
    db.add(
        LiveStream(
            id=str(stream_id),
            asset_id=str(asset_id),
            stream_key=f"match-{stream_id.hex[:8]}",
            hls_manifest_url="https://cdn.test/live.m3u8",
            s3_prefix=f"streams/{stream_id}/segments/",
            status="active",
        )
    )
    await db.commit()
    return stream_id


@pytest.mark.asyncio
async def test_parse_hls_manifest_extracts_segments(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = "#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:10\n" + "\n".join(
        f"#EXTINF:4.0,\nseg_{i}.ts" for i in range(6)
    )
    monkeypatch.setattr(
        live_stream.httpx,
        "AsyncClient",
        lambda **kwargs: FakeAsyncClient({"https://cdn.test/live.m3u8": FakeResponse(manifest)}, **kwargs),
    )

    segments = await live_stream.fetch_hls_segments("https://cdn.test/live.m3u8")

    assert len(segments) == 5
    assert segments[0].sequence == 11
    assert all(segment.url for segment in segments)


@pytest.mark.asyncio
async def test_parse_hls_master_manifest_picks_highest_bitrate(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    master = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=500000
low.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3000000
high.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1500000
mid.m3u8
"""
    variant = "#EXTM3U\n#EXTINF:4.0,\nseg.ts\n"
    responses = {
        "https://cdn.test/master.m3u8": FakeResponse(master),
        "https://cdn.test/high.m3u8": FakeResponse(variant),
    }
    monkeypatch.setattr(
        live_stream.httpx,
        "AsyncClient",
        lambda **kwargs: FakeAsyncClient(responses, seen, **kwargs),
    )

    await live_stream.fetch_hls_segments("https://cdn.test/master.m3u8")

    assert seen == ["https://cdn.test/master.m3u8", "https://cdn.test/high.m3u8"]


@pytest.mark.asyncio
async def test_parse_hls_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        live_stream.httpx,
        "AsyncClient",
        lambda **kwargs: FakeAsyncClient({"https://cdn.test/missing.m3u8": FakeResponse(status_code=404)}, **kwargs),
    )

    with pytest.raises(LiveStreamError):
        await live_stream.fetch_hls_segments("https://cdn.test/missing.m3u8")


@pytest.mark.asyncio
async def test_mock_suspect_urls_return_fixture_segments() -> None:
    segments = await live_stream.fetch_hls_segments(MOCK_SUSPECT_URLS[0], max_segments=3)

    assert len(segments) == 3
    assert "sample_clip.mp4" in segments[0].url


@pytest.mark.asyncio
async def test_watermark_segment_downloads_uploads_s3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asset_id = uuid4()
    engine, Session = await _make_db(tmp_path)
    async with Session() as db:
        await _insert_asset(db, asset_id)
        stream_id = await _insert_stream(db, asset_id)

        class Body:
            def read(self) -> bytes:
                return b"ts"

        class FakeS3:
            put_calls: list[dict] = []

            def get_object(self, **kwargs):
                return {"Body": Body()}

            def put_object(self, **kwargs):
                self.put_calls.append(kwargs)

        class FakeCF:
            calls: list[dict] = []

            def create_invalidation(self, **kwargs):
                self.calls.append(kwargs)

        fake_s3 = FakeS3()
        fake_cf = FakeCF()
        monkeypatch.setattr(live_stream, "s3", fake_s3)
        monkeypatch.setattr(live_stream, "cf", fake_cf)
        monkeypatch.setattr(live_stream.settings, "live_bucket", "sports-ip-live")
        monkeypatch.setattr(live_stream.settings, "cloudfront_distribution_id", "DIST")
        monkeypatch.setattr(live_stream.settings, "watermark_secret_key", KEY)
        monkeypatch.setattr(live_stream, "_extract_first_iframe", lambda ts: b"jpg")
        monkeypatch.setattr(live_stream, "_render_segment_with_frame", lambda ts, frame_path: b"watermarked")
        monkeypatch.setattr(live_stream.cv2, "imdecode", lambda raw, flag: np.zeros((16, 16, 3), dtype=np.uint8))
        monkeypatch.setattr(live_stream.cv2, "imencode", lambda ext, frame: (True, np.array([1, 2, 3], dtype=np.uint8)))
        monkeypatch.setattr(live_stream.WatermarkService, "embed", lambda frame, payload, key, alpha: frame)

        row = await LiveStreamService.watermark_segment(stream_id, "seg_001.ts", 42, db)

        assert row is not None
        assert fake_s3.put_calls[0]["Bucket"] == "sports-ip-live"
        assert fake_s3.put_calls[0]["Key"].endswith("/seg_001.ts")
        assert fake_cf.calls
        result = await db.execute(select(LiveSegmentWatermark))
        assert result.scalar_one().payload == 42
    await engine.dispose()


@pytest.mark.asyncio
async def test_watermark_segment_skips_no_iframe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asset_id = uuid4()
    engine, Session = await _make_db(tmp_path)
    async with Session() as db:
        await _insert_asset(db, asset_id)
        stream_id = await _insert_stream(db, asset_id)

        class Body:
            def read(self) -> bytes:
                return b"ts"

        class FakeS3:
            uploaded = False

            def get_object(self, **kwargs):
                return {"Body": Body()}

            def put_object(self, **kwargs):
                self.uploaded = True

        fake_s3 = FakeS3()
        monkeypatch.setattr(live_stream, "s3", fake_s3)
        monkeypatch.setattr(live_stream.settings, "live_bucket", "sports-ip-live")
        monkeypatch.setattr(live_stream, "_extract_first_iframe", lambda ts: b"")

        assert await LiveStreamService.watermark_segment(stream_id, "seg_001.ts", 42, db) is None
        assert fake_s3.uploaded is False
    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_suspect_stream_fingerprint_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asset_id = uuid4()
    engine, Session = await _make_db(tmp_path)
    async with Session() as db:
        await _insert_asset(db, asset_id)
        stream_id = await _insert_stream(db, asset_id)
        fake_redis = FakeRedis()
        monkeypatch.setattr(live_stream, "redis_client", fake_redis)

        class FakeEvidence:
            def delay(self, match_id: str) -> None:
                return None

        import app.workers.evidence_task as evidence_task

        monkeypatch.setattr(evidence_task, "generate", FakeEvidence())

        monkeypatch.setattr(live_stream.settings, "watermark_secret_key", KEY)
        monkeypatch.setattr(live_stream.settings, "inbound_max_segments", 1)

        async def fake_fetch(url, max_segments=5):
            return [HLSSegment("https://bad.test/seg.ts", 1, 4.0)]

        monkeypatch.setattr(live_stream, "fetch_hls_segments", fake_fetch)

        async def fake_download(client, segment, dest):
            dest.write_bytes(b"ts")
            return dest

        async def fake_fp(path, stream_asset_id=None):
            return [FingerprintMatch(asset_id=asset_id, confidence=0.8, start_ms=0, end_ms=4000, match_type="frame")]

        monkeypatch.setattr(live_stream, "_download_segment", fake_download)
        monkeypatch.setattr(live_stream, "_extract_first_iframe", lambda ts: b"")
        monkeypatch.setattr(live_stream, "_fingerprint_match", fake_fp)

        violation = await LiveStreamService.scan_suspect_stream("https://bad.test/live.m3u8", stream_id, db)

        assert violation is not None
        assert violation.confidence == 0.8
        assert violation.match_type == "fingerprint"
        assert violation.status == "dmca_sent"
    await engine.dispose()


@pytest.mark.asyncio
async def test_scan_suspect_stream_no_match_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asset_id = uuid4()
    engine, Session = await _make_db(tmp_path)
    async with Session() as db:
        await _insert_asset(db, asset_id)
        stream_id = await _insert_stream(db, asset_id)

        monkeypatch.setattr(live_stream.settings, "watermark_secret_key", KEY)

        async def fake_fetch(url, max_segments=5):
            return [HLSSegment("x", 1, 4.0)]

        monkeypatch.setattr(live_stream, "fetch_hls_segments", fake_fetch)

        async def fake_download(client, segment, dest):
            dest.write_bytes(b"ts")
            return dest

        async def fake_fp(path, stream_asset_id=None):
            return []

        monkeypatch.setattr(live_stream, "_download_segment", fake_download)
        monkeypatch.setattr(live_stream, "_extract_first_iframe", lambda ts: b"")
        monkeypatch.setattr(live_stream, "_fingerprint_match", fake_fp)

        assert await LiveStreamService.scan_suspect_stream("https://bad.test/live.m3u8", stream_id, db) is None
        assert (await db.execute(select(LiveViolation))).scalar_one_or_none() is None
    await engine.dispose()


@pytest.mark.asyncio
async def test_trigger_live_dmca_creates_match_row_and_publishes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    asset_id = uuid4()
    engine, Session = await _make_db(tmp_path)
    fake_redis = FakeRedis()
    monkeypatch.setattr(live_stream, "redis_client", fake_redis)

    class FakeEvidence:
        calls: list[str] = []

        def delay(self, match_id: str) -> None:
            self.calls.append(match_id)

    import app.workers.evidence_task as evidence_task

    fake_evidence = FakeEvidence()
    monkeypatch.setattr(evidence_task, "generate", fake_evidence)

    async with Session() as db:
        await _insert_asset(db, asset_id)
        stream_id = await _insert_stream(db, asset_id)
        violation = LiveViolation(
            stream_id=str(stream_id),
            asset_id=str(asset_id),
            source_url="https://bad.test/live.m3u8",
            platform="web",
            confidence=0.75,
            match_type="fingerprint",
            severity="medium",
            status="new",
            detected_at=datetime.now(UTC),
        )
        db.add(violation)
        await db.commit()
        await db.refresh(violation)

        await LiveStreamService.trigger_live_dmca(UUID(violation.id), db)

        match = (await db.execute(select(Match))).scalar_one()
        assert match.asset_id == str(asset_id)
        assert match.source_url == "https://bad.test/live.m3u8"
        assert fake_evidence.calls == [match.id]
        assert fake_redis.published[0][0] == "match.created"
    await engine.dispose()


@pytest.mark.asyncio
async def test_register_stream_api_creates_db_row(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app

    asset_id = uuid4()
    engine, Session = await _make_db(tmp_path)
    fake_redis = FakeRedis()
    monkeypatch.setattr(live_stream, "redis_client", fake_redis)

    async with Session() as db:
        await _insert_asset(db, asset_id)

    async def override_session():
        async with Session() as session:
            yield session

    async def override_token():
        return None

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[verify_token] = override_token
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/live-streams/register",
                json={
                    "asset_id": str(asset_id),
                    "stream_key": "match-live",
                    "hls_manifest_url": "https://cdn.test/live.m3u8",
                    "s3_prefix": "streams/live/segments/",
                },
            )
        assert response.status_code == 201
        async with Session() as db:
            stream = (await db.execute(select(LiveStream))).scalar_one()
            assert stream.status == "active"
        assert fake_redis.published[0][0] == "stream.registered"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
