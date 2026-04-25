import asyncio
import io
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.base import Base
from app.models.asset import Asset
from app.models.visual import VisualAssetFrame
from app.services import visual_discovery
from app.services.visual_discovery import (
    ClipEmbedder,
    ExtractedVisualLink,
    ScoredCandidate,
    VisualDiscoveryService,
    VisualLinkParser,
    _dedupe_scored,
    _hamming_hex,
    _phash_image,
)


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _image_bytes(color: tuple[int, int, int]) -> bytes:
    image = visual_discovery.Image.new("RGB", (64, 64), color=color)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


async def _make_db(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'visual.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    return engine, Session


def test_phash_distance_ranks_similar_image_above_unrelated() -> None:
    base = visual_discovery.Image.new("RGB", (64, 64), color=(20, 100, 200))
    similar = visual_discovery.Image.new("RGB", (64, 64), color=(22, 102, 198))
    unrelated = visual_discovery.Image.new("RGB", (64, 64), color=(240, 40, 40))

    base_hash = _phash_image(base)
    similar_distance = _hamming_hex(base_hash, _phash_image(similar))
    unrelated_distance = _hamming_hex(base_hash, _phash_image(unrelated))

    assert similar_distance <= unrelated_distance


def test_clip_embedder_skips_when_dependencies_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(visual_discovery, "clip", None)
    monkeypatch.setattr(visual_discovery, "torch", None)

    embedder = ClipEmbedder()

    assert embedder.embed(visual_discovery.Image.new("RGB", (8, 8))) is None


def test_html_thumbnail_extraction_handles_common_sources() -> None:
    parser = VisualLinkParser("https://example.test/page")
    parser.feed(
        """
        <meta property="og:image" content="/og.jpg">
        <img src="/thumb.png">
        <video poster="/poster.webp" src="/clip.mp4"></video>
        <a href="/direct.mp4">clip</a>
        """
    )

    urls = {link.image_url for link in parser.links}
    sources = {link.source_url for link in parser.links}

    assert "https://example.test/og.jpg" in urls
    assert "https://example.test/thumb.png" in urls
    assert "https://example.test/poster.webp" in urls
    assert "https://example.test/page" in sources
    assert "https://example.test/direct.mp4" in sources


def test_candidate_deduplication_keeps_highest_score() -> None:
    candidates = [
        ScoredCandidate("https://x.test/v", "https://x.test", "web", "a.jpg", 10, None, 0.3),
        ScoredCandidate("https://x.test/v", "https://x.test", "web", "b.jpg", 2, None, 0.9),
    ]

    deduped = _dedupe_scored(candidates)

    assert len(deduped) == 1
    assert deduped[0].thumbnail_url == "b.jpg"


def test_index_asset_creates_visual_signatures(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        asset_id = uuid4()
        engine, Session = await _make_db(tmp_path)
        async with Session() as session:
            session.add(
                Asset(
                    id=str(asset_id),
                    title="Final",
                    status="ready",
                    fingerprint_status="ready",
                    watermark_status="ready",
                    video_path="clip.mp4",
                )
            )
            await session.commit()
            frame = tmp_path / "frame.png"
            frame.write_bytes(_image_bytes((10, 20, 30)))

            async def fake_extract(self, video_path: str, frames_dir: Path):
                return [frame]

            monkeypatch.setattr(VisualDiscoveryService, "_extract_asset_frames", fake_extract)
            service = VisualDiscoveryService(session)

            count = await service.index_asset(asset_id, "clip.mp4")

            assert count == 1
            stored = (await session.execute(visual_discovery.select(VisualAssetFrame))).scalars().all()
            assert len(stored) == 1
            assert stored[0].asset_id == str(asset_id)
        await engine.dispose()

    asyncio.run(run())


def test_discover_scores_thumbnail_and_returns_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        asset_id = uuid4()
        engine, Session = await _make_db(tmp_path)
        base_hash = _phash_image(visual_discovery.Image.new("RGB", (64, 64), color=(10, 80, 120)))
        async with Session() as session:
            session.add(VisualAssetFrame(asset_id=str(asset_id), timestamp_ms=0, phash=base_hash))
            await session.commit()

            async def fake_seed(self, query: str):
                return ["https://source.test/page"]

            html = '<meta property="og:image" content="https://source.test/thumb.png">'

            def handler(request: httpx.Request) -> httpx.Response:
                if str(request.url).endswith("/page"):
                    return httpx.Response(200, headers={"content-type": "text/html"}, text=html)
                return httpx.Response(200, headers={"content-type": "image/png"}, content=_image_bytes((10, 80, 120)))

            monkeypatch.setenv("VISUAL_PHASH_THRESHOLD", "18")
            get_settings.cache_clear()
            monkeypatch.setattr(VisualDiscoveryService, "_seed_page_urls", fake_seed)
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            service = VisualDiscoveryService(session, client=client)

            candidates = await service.discover(asset_id, "anything", max_candidates=5)

            assert len(candidates) == 1
            assert candidates[0].source_url == "https://source.test/page"
            assert candidates[0].thumbnail_url == "https://source.test/thumb.png"
            await client.aclose()
        await engine.dispose()

    asyncio.run(run())


def test_visual_crawl_budget_limits_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        class SessionStub:
            pass

        monkeypatch.setenv("VISUAL_CRAWL_MAX_PAGES", "2")
        monkeypatch.setenv("CRAWLER_WATCHLIST_URLS", "https://a.test,https://b.test,https://c.test")
        get_settings.cache_clear()

        async def fake_watchlist(self):
            return ["https://db.test"]

        monkeypatch.setattr(VisualDiscoveryService, "_watchlist_urls", fake_watchlist)
        service = VisualDiscoveryService(SessionStub())

        assert await service._seed_page_urls("") == ["https://db.test"]

    asyncio.run(run())
