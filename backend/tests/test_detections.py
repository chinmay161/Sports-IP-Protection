from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api import detections
from app.core.auth import verify_token
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.alert import Alert  # noqa: F401
from app.models.asset import Asset
from app.models.match import Match, MatchSegment
from app.models.watermark import WatermarkRegistry  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'detections.db'}")
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


async def _asset(db: AsyncSession, asset_id: UUID | None = None, status: str = "ready") -> Asset:
    asset = Asset(
        id=str(asset_id or uuid4()),
        title="Test Asset",
        description=None,
        status=status,
        fingerprint_status=status,
        watermark_status=status,
        video_path="clip.mp4",
    )
    db.add(asset)
    await db.flush()
    return asset


async def _match(
    db: AsyncSession,
    asset_id: str,
    *,
    severity: str = "medium",
    platform: str = "web",
    status: str = "new",
    geo_country: str | None = None,
    detected_at: datetime | None = None,
) -> Match:
    match = Match(
        id=str(uuid4()),
        asset_id=asset_id,
        source_url=f"https://{platform}.example/{uuid4().hex}",
        platform=platform,
        confidence=0.9,
        match_type="fingerprint",
        severity=severity,
        duration_matched_ms=5000,
        status=status,
        geo_country=geo_country,
        detected_at=detected_at or datetime.now(UTC),
    )
    db.add(match)
    await db.flush()
    return match


async def test_list_detections_returns_all(client, session_factory):
    async with session_factory() as db:
        asset = await _asset(db)
        for index in range(3):
            await _match(db, asset.id, detected_at=datetime.now(UTC) + timedelta(seconds=index))
        await db.commit()

    response = await client.get("/detections")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3


async def test_list_detections_filter_severity(client, session_factory):
    async with session_factory() as db:
        asset = await _asset(db)
        await _match(db, asset.id, severity="critical")
        await _match(db, asset.id, severity="critical")
        await _match(db, asset.id, severity="medium")
        await db.commit()

    response = await client.get("/detections", params={"severity": "critical"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert all(item["severity"] == "critical" for item in body["items"])


async def test_list_detections_filter_platform(client, session_factory):
    async with session_factory() as db:
        asset = await _asset(db)
        await _match(db, asset.id, platform="youtube")
        await _match(db, asset.id, platform="tiktok")
        await db.commit()

    response = await client.get("/detections", params={"platform": "tiktok"})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["platform"] == "tiktok"


async def test_list_detections_limit_enforced(client):
    response = await client.get("/detections", params={"limit": 201})
    assert response.status_code == 422


async def test_get_detection_by_id(client, session_factory):
    async with session_factory() as db:
        asset = await _asset(db)
        match = await _match(db, asset.id, severity="high")
        db.add_all(
            [
                MatchSegment(
                    match_id=match.id,
                    asset_start_ms=0,
                    asset_end_ms=1000,
                    source_start_ms=100,
                    source_end_ms=1100,
                    frame_run_length=12,
                ),
                MatchSegment(
                    match_id=match.id,
                    asset_start_ms=2000,
                    asset_end_ms=3000,
                    source_start_ms=5000,
                    source_end_ms=6000,
                    frame_run_length=8,
                ),
            ]
        )
        await db.commit()

    response = await client.get(f"/detections/{match.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == match.id
    assert body["severity"] == "high"
    assert len(body["segments"]) == 2


async def test_get_detection_404(client):
    response = await client.get(f"/detections/{uuid4()}")
    assert response.status_code == 404


async def test_stats_by_severity(client, session_factory):
    async with session_factory() as db:
        asset = await _asset(db)
        for _ in range(2):
            await _match(db, asset.id, severity="critical")
        for _ in range(3):
            await _match(db, asset.id, severity="medium")
        await db.commit()

    response = await client.get("/detections/stats")
    assert response.status_code == 200
    by_severity = response.json()["by_severity"]
    assert by_severity["critical"] == 2
    assert by_severity["medium"] == 3
    assert by_severity["low"] == 0


async def test_stats_top_countries(client, session_factory):
    async with session_factory() as db:
        asset = await _asset(db)
        for _ in range(3):
            await _match(db, asset.id, geo_country="IN")
        for _ in range(2):
            await _match(db, asset.id, geo_country="BR")
        await db.commit()

    response = await client.get("/detections/stats")
    assert response.status_code == 200
    assert response.json()["top_infringing_countries"][0]["country"] == "IN"


async def test_acknowledge_sets_status(client, session_factory):
    async with session_factory() as db:
        asset = await _asset(db)
        match = await _match(db, asset.id, status="new")
        await db.commit()

    response = await client.post(f"/detections/{match.id}/acknowledge", json={"note": "reviewed"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "acknowledged"
    assert body["alerted_at"] is not None


async def test_acknowledge_conflict(client, session_factory):
    async with session_factory() as db:
        asset = await _asset(db)
        match = await _match(db, asset.id, status="resolved")
        await db.commit()

    response = await client.post(f"/detections/{match.id}/acknowledge", json={"note": None})
    assert response.status_code == 409


async def test_dmca_enqueues_task(client, session_factory, monkeypatch: pytest.MonkeyPatch):
    async with session_factory() as db:
        asset = await _asset(db)
        match = await _match(db, asset.id, status="new")
        await db.commit()

    calls: list[str] = []

    def fake_delay(match_id: str):
        calls.append(match_id)
        return SimpleNamespace(id="evidence-task-id")

    monkeypatch.setattr(detections.evidence_generate, "delay", fake_delay)
    response = await client.post(f"/detections/{match.id}/dmca")
    assert response.status_code == 200
    assert response.json()["status"] == "dmca_sent"
    assert calls == [match.id]


async def test_scan_endpoint_queues_task(client, session_factory, monkeypatch: pytest.MonkeyPatch):
    async with session_factory() as db:
        asset = await _asset(db, status="ready")
        await db.commit()

    calls: list[tuple[str, int]] = []

    def fake_delay(asset_id: str, max_per_platform: int):
        calls.append((asset_id, max_per_platform))
        return SimpleNamespace(id="scan-task-id")

    monkeypatch.setattr(detections.scan_asset, "delay", fake_delay)
    response = await client.post(
        "/detections/scan",
        json={"asset_id": asset.id, "max_per_platform": 5},
    )
    assert response.status_code == 200
    assert response.json() == {"task_id": "scan-task-id", "status": "queued"}
    assert calls == [(asset.id, 5)]


async def test_scan_endpoint_404_unknown_asset(client):
    response = await client.post(
        "/detections/scan",
        json={"asset_id": str(uuid4()), "max_per_platform": 5},
    )
    assert response.status_code == 404
