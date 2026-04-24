from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.auth import verify_token
from app.db.base import Base
from app.db.session import get_db_session
from app.main import app
from app.models.alert import Alert  # noqa: F401
from app.models.asset import Asset
from app.models.comment import CaseComment  # noqa: F401
from app.models.match import Match
from app.models.watermark import WatermarkRegistry  # noqa: F401

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'propagation.db'}")
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


async def _seed_matches(session_factory) -> tuple[str, list[str]]:
    asset_id = str(uuid4())
    match_ids = [str(uuid4()), str(uuid4()), str(uuid4())]
    start = datetime(2026, 4, 24, 8, 15, tzinfo=UTC)
    async with session_factory() as db:
        db.add(
            Asset(
                id=asset_id,
                title="Propagation Asset",
                description=None,
                status="ready",
                fingerprint_status="ready",
                watermark_status="ready",
                video_path="clip.mp4",
            )
        )
        for index, match_id in enumerate(match_ids):
            db.add(
                Match(
                    id=match_id,
                    asset_id=asset_id,
                    source_url=f"https://platform{index}.example/video",
                    platform=["telegram", "youtube", "web"][index],
                    confidence=0.9 - (index * 0.1),
                    match_type="fingerprint",
                    severity=["critical", "high", "medium"][index],
                    source_channel=f"channel-{index}",
                    view_count=(index + 1) * 100,
                    duration_matched_ms=5000,
                    status="new",
                    geo_country=["US", "IN", None][index],
                    detected_at=start + timedelta(minutes=30 * index),
                )
            )
        await db.commit()
    return asset_id, match_ids


async def test_propagation_graph_uses_matches(client, session_factory) -> None:
    _, match_ids = await _seed_matches(session_factory)

    response = await client.get(f"/propagation/{match_ids[0]}/graph")

    assert response.status_code == 200
    body = response.json()
    assert body["match_id"] == match_ids[0]
    assert body["meta"]["node_count"] == 3
    assert body["meta"]["edge_count"] == 2
    assert body["nodes"][0]["type"] == "origin"
    assert body["nodes"][1]["platform"] == "youtube"


async def test_propagation_timeline_buckets_matches(client, session_factory) -> None:
    _, match_ids = await _seed_matches(session_factory)

    response = await client.get(f"/propagation/{match_ids[0]}/timeline")

    assert response.status_code == 200
    body = response.json()
    assert body["bucket_size_ms"] == 3_600_000
    assert body["buckets"][0]["new_nodes"] == 2
    assert body["buckets"][0]["cumulative_views"] == 300


async def test_propagation_summary_uses_asset_matches(client, session_factory) -> None:
    asset_id, _ = await _seed_matches(session_factory)

    response = await client.get(f"/propagation/{UUID(asset_id)}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["total_infringing_copies"] == 3
    assert body["total_estimated_views"] == 600
    assert body["platforms_reached"] == ["telegram", "web", "youtube"]
    assert body["countries_reached"] == 2
