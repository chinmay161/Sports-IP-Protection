from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.alert import Alert  # noqa: F401
from app.models.asset import Asset
from app.models.comment import CaseComment  # noqa: F401
from app.models.match import Match
from app.models.watermark import WatermarkRegistry  # noqa: F401
from app.schemas.propagation import GraphNode
from app.services.propagation import (
    PropagationError,
    _assign_node_types,
    _build_timeline,
    _infer_edges,
    get_graph,
    get_summary,
    get_timeline,
)


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


def _node(
    *,
    node_id: str | None = None,
    platform: str = "youtube",
    detected_at: datetime | None = None,
    view_count: int | None = 100,
) -> GraphNode:
    return GraphNode(
        id=node_id or str(uuid4()),
        type="origin",
        platform=platform,
        channel=None,
        url="https://example.test/video",
        view_count=view_count,
        confidence=0.9,
        severity="high",
        geo_country="US",
        detected_at=detected_at or datetime(2026, 4, 24, 8, 0, tzinfo=UTC),
        status="new",
    )


def test_infer_edges_first_node_has_no_edge() -> None:
    assert _infer_edges([_node()]) == []


def test_infer_edges_cross_platform_is_repost() -> None:
    start = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)
    node_a = _node(node_id=str(uuid4()), platform="youtube", detected_at=start)
    node_b = _node(node_id=str(uuid4()), platform="tiktok", detected_at=start + timedelta(hours=1))

    edges = _infer_edges([node_a, node_b])

    assert edges[0].relation == "repost"
    assert edges[0].source == node_a.id
    assert edges[0].target == node_b.id


def test_infer_edges_same_platform_is_mirror() -> None:
    start = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)
    edges = _infer_edges(
        [
            _node(platform="youtube", detected_at=start),
            _node(platform="youtube", detected_at=start + timedelta(hours=1)),
        ]
    )

    assert edges[0].relation == "mirror"


def test_infer_edges_over_48h_is_unknown() -> None:
    start = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)
    edges = _infer_edges(
        [
            _node(platform="youtube", detected_at=start),
            _node(platform="tiktok", detected_at=start + timedelta(hours=49)),
        ]
    )

    assert edges[0].relation == "unknown"


def test_infer_edges_delta_ms_is_positive() -> None:
    start = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)
    edges = _infer_edges(
        [
            _node(platform="youtube", detected_at=start),
            _node(platform="tiktok", detected_at=start + timedelta(minutes=1)),
        ]
    )

    assert all(edge.delta_ms > 0 for edge in edges)


def test_infer_edges_deterministic_id() -> None:
    start = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)
    nodes = [
        _node(node_id=str(uuid4()), platform="youtube", detected_at=start),
        _node(node_id=str(uuid4()), platform="tiktok", detected_at=start + timedelta(hours=1)),
    ]

    assert _infer_edges(nodes)[0].id == _infer_edges(nodes)[0].id


def test_assign_types_first_node_is_origin() -> None:
    nodes = [
        _node(detected_at=datetime(2026, 4, 24, 9, 0, tzinfo=UTC)),
        _node(detected_at=datetime(2026, 4, 24, 8, 0, tzinfo=UTC)),
    ]

    assert _assign_node_types(nodes)[0].type == "origin"


def test_assign_types_cross_platform_repost() -> None:
    start = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)
    nodes = [
        _node(platform="youtube", detected_at=start),
        _node(platform="tiktok", detected_at=start + timedelta(hours=1)),
    ]

    assert _assign_node_types(nodes)[1].type == "repost"


def test_build_timeline_single_node() -> None:
    node = _node()

    timeline = _build_timeline([node])

    assert len(timeline.buckets) == 1
    assert timeline.velocity_index == 0.0


def test_build_timeline_hourly_buckets() -> None:
    start = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)
    timeline = _build_timeline(
        [
            _node(detected_at=start),
            _node(detected_at=start + timedelta(minutes=30)),
            _node(detected_at=start + timedelta(minutes=90)),
        ]
    )

    assert len(timeline.buckets) == 2
    assert timeline.buckets[0].new_nodes == 2
    assert timeline.buckets[1].new_nodes == 1


def test_build_timeline_cumulative_views() -> None:
    start = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)
    timeline = _build_timeline(
        [
            _node(detected_at=start, view_count=100),
            _node(detected_at=start + timedelta(minutes=30), view_count=200),
            _node(detected_at=start + timedelta(minutes=90), view_count=None),
        ]
    )

    assert timeline.buckets[-1].cumulative_views == 300


def test_build_timeline_peak_bucket() -> None:
    start = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)
    timeline = _build_timeline(
        [
            _node(detected_at=start),
            _node(detected_at=start + timedelta(hours=1, minutes=1)),
            _node(detected_at=start + timedelta(hours=1, minutes=2)),
        ]
    )

    assert timeline.peak_bucket == timeline.buckets[1].bucket_start


def test_build_timeline_velocity_index() -> None:
    start = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)
    nodes = [_node(detected_at=start)]
    nodes.extend(_node(detected_at=start + timedelta(hours=1, minutes=i)) for i in range(5))

    timeline = _build_timeline(nodes)

    assert timeline.velocity_index == 5.0


async def _add_asset(db: AsyncSession, asset_id: str) -> None:
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


async def _seed_matches(
    session_factory,
    *,
    platforms: list[str] | None = None,
    view_counts: list[int] | None = None,
    offsets: list[timedelta] | None = None,
    include_low_confidence: bool = False,
) -> tuple[str, list[str]]:
    asset_id = str(uuid4())
    platforms = platforms or ["youtube", "youtube", "tiktok"]
    view_counts = view_counts or [1000, 2000, 3000]
    offsets = offsets or [timedelta(0), timedelta(hours=1), timedelta(hours=2)]
    match_ids = [str(uuid4()) for _ in platforms]
    start = datetime(2026, 4, 24, 8, 0, tzinfo=UTC)

    async with session_factory() as db:
        await _add_asset(db, asset_id)
        for index, match_id in enumerate(match_ids):
            db.add(
                Match(
                    id=match_id,
                    asset_id=asset_id,
                    source_url=f"https://{platforms[index]}.example/video/{index}",
                    platform=platforms[index],
                    confidence=0.9,
                    match_type="fingerprint",
                    severity="high",
                    source_channel=f"channel-{index}",
                    view_count=view_counts[index],
                    duration_matched_ms=5000,
                    status="new",
                    geo_country=["US", "IN", "GB"][index % 3],
                    detected_at=start + offsets[index],
                )
            )
        if include_low_confidence:
            db.add(
                Match(
                    id=str(uuid4()),
                    asset_id=asset_id,
                    source_url="https://low.example/video",
                    platform="telegram",
                    confidence=0.49,
                    match_type="fingerprint",
                    severity="low",
                    source_channel="low-confidence",
                    view_count=9999,
                    duration_matched_ms=5000,
                    status="new",
                    geo_country="CA",
                    detected_at=start + timedelta(minutes=10),
                )
            )
        await db.commit()

    return asset_id, match_ids


@pytest.mark.asyncio
async def test_get_graph_returns_all_asset_matches(session_factory) -> None:
    _, match_ids = await _seed_matches(session_factory, include_low_confidence=True)

    async with session_factory() as db:
        graph = await get_graph(UUID(match_ids[0]), db)

    assert len(graph.nodes) == 3
    assert len(graph.edges) == 2


@pytest.mark.asyncio
async def test_get_graph_meta_platform_spread(session_factory) -> None:
    _, match_ids = await _seed_matches(
        session_factory,
        platforms=["youtube", "youtube", "tiktok"],
    )

    async with session_factory() as db:
        graph = await get_graph(UUID(match_ids[0]), db)

    assert graph.meta.platform_spread == {"youtube": 2, "tiktok": 1}


@pytest.mark.asyncio
async def test_get_graph_raises_for_unknown_match(session_factory) -> None:
    async with session_factory() as db:
        with pytest.raises(PropagationError):
            await get_graph(uuid4(), db)


@pytest.mark.asyncio
async def test_get_timeline_bucket_count(session_factory) -> None:
    _, match_ids = await _seed_matches(
        session_factory,
        offsets=[timedelta(0), timedelta(hours=3), timedelta(hours=6)],
    )

    async with session_factory() as db:
        timeline = await get_timeline(UUID(match_ids[0]), db)

    assert len(timeline.buckets) >= 3


@pytest.mark.asyncio
async def test_get_summary_totals(session_factory) -> None:
    asset_id, _ = await _seed_matches(
        session_factory,
        view_counts=[1000, 2000, 3000],
        include_low_confidence=True,
    )

    async with session_factory() as db:
        summary = await get_summary(UUID(asset_id), db)

    assert summary.total_estimated_views == 6000
    assert summary.total_infringing_copies == 3


@pytest.mark.asyncio
async def test_get_summary_fastest_repost(session_factory) -> None:
    asset_id, _ = await _seed_matches(
        session_factory,
        platforms=["youtube", "tiktok"],
        view_counts=[1000, 2000],
        offsets=[timedelta(0), timedelta(hours=2)],
    )

    async with session_factory() as db:
        summary = await get_summary(UUID(asset_id), db)

    assert summary.fastest_repost_ms == 7_200_000


@pytest.mark.asyncio
async def test_get_summary_raises_for_unknown_asset(session_factory) -> None:
    async with session_factory() as db:
        with pytest.raises(PropagationError):
            await get_summary(uuid4(), db)
