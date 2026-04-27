import asyncio
import re
from pathlib import Path
from uuid import UUID

import pytest

from app.services import crawler
from app.services.crawler import CandidateVideo, CrawlerError, CrawlerService, TikTokMockAdapter, YouTubeMockAdapter


@pytest.fixture(autouse=True)
def clear_settings_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CRAWLER_MODE", "mock")
    monkeypatch.setenv("CRAWLER_DISCOVERY_MODE", "hybrid")
    monkeypatch.delenv("CRAWLER_WATCHLIST_URLS", raising=False)
    crawler.get_settings.cache_clear()
    monkeypatch.setattr(crawler, "_default_service", CrawlerService())
    yield
    crawler.get_settings.cache_clear()


def test_youtube_platform_and_url_format() -> None:
    results = asyncio.run(crawler.crawl("youtube", "test", 10))

    assert all(candidate.platform == "youtube" for candidate in results)
    assert all(candidate.geo_country is None for candidate in results)
    assert all(
        re.match(r"^https://www\.youtube\.com/watch\?v=[A-Za-z0-9]{11}$", candidate.source_url)
        for candidate in results
    )


def test_crawler_populates_resolved_geo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crawler, "country_for_url", lambda url: "US")

    results = asyncio.run(crawler.crawl("web", "test", 3))

    assert {candidate.geo_country for candidate in results} == {"US"}


def test_tiktok_views_skew_higher_than_youtube() -> None:
    youtube = YouTubeMockAdapter().generate(200)
    tiktok = TikTokMockAdapter().generate(200)

    youtube_mean = sum(candidate.view_count or 0 for candidate in youtube) / len(youtube)
    tiktok_mean = sum(candidate.view_count or 0 for candidate in tiktok) / len(tiktok)

    assert tiktok_mean > youtube_mean


def test_crawl_all_deduplicates() -> None:
    results = asyncio.run(crawler.crawl_all("test", 10))
    source_urls = [candidate.source_url for candidate in results]

    assert len(source_urls) == len(set(source_urls))


def test_crawl_all_all_platforms_represented() -> None:
    results = asyncio.run(crawler.crawl_all("test", 10))

    assert {"youtube", "tiktok", "telegram", "web"} <= {candidate.platform for candidate in results}


def test_crawler_defaults_to_mock_mode() -> None:
    service = CrawlerService()

    assert service.mode == "mock"
    assert service.adapters.keys() == {"youtube", "tiktok", "telegram", "web"}
    assert isinstance(service.adapters["youtube"], YouTubeMockAdapter)


def test_crawler_can_use_real_mode() -> None:
    service = CrawlerService(mode="real")

    assert service.mode == "real"
    assert service.adapters.keys() == {"youtube", "tiktok", "telegram", "web"}
    assert not isinstance(service.adapters["youtube"], YouTubeMockAdapter)


def test_crawler_rejects_unknown_mode() -> None:
    with pytest.raises(CrawlerError):
        CrawlerService(mode="mystery")


def test_real_mode_delegates_query_to_search_adapter() -> None:
    class FakeSearchAdapter:
        async def search(self, query: str, max_results: int):
            return [
                CandidateVideo(
                    source_url=f"https://example.com/{query}/{max_results}",
                    platform="web",
                    channel="example.com",
                    view_count=None,
                    duration_ms=None,
                    geo_country=None,
                    thumbnail_url=None,
                    uploaded_at=None,
                )
            ]

    service = CrawlerService(mode="real")
    service.adapters = {"web": FakeSearchAdapter()}

    results = asyncio.run(service.crawl("web", "championship", 2))

    assert results[0].source_url == "https://example.com/championship/2"


def test_youtube_metadata_normalizes_flat_search_result() -> None:
    candidate = crawler._metadata_to_candidate(
        {
            "id": "abc123XYZ90",
            "duration": 12,
            "channel": "Sports Channel",
            "view_count": 50,
        },
        "youtube",
    )

    assert candidate is not None
    assert candidate.source_url == "https://www.youtube.com/watch?v=abc123XYZ90"
    assert candidate.duration_ms == 12_000


def test_hybrid_discovery_combines_and_deduplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    asset_id = "00000000-0000-0000-0000-000000000001"

    async def fake_search(self, query: str, max_per_platform: int):
        return [
            CandidateVideo(
                source_url="https://example.test/shared.mp4",
                platform="web",
                channel=None,
                view_count=None,
                duration_ms=None,
                geo_country=None,
                thumbnail_url=None,
                uploaded_at=None,
            )
        ]

    async def fake_visual(self, query: str, received_asset_id):
        assert str(received_asset_id) == asset_id
        return [
            CandidateVideo(
                source_url="https://example.test/shared.mp4",
                platform="web",
                channel=None,
                view_count=None,
                duration_ms=None,
                geo_country=None,
                thumbnail_url="https://example.test/thumb.jpg",
                uploaded_at=None,
            ),
            CandidateVideo(
                source_url="https://example.test/visual.mp4",
                platform="web",
                channel=None,
                view_count=None,
                duration_ms=None,
                geo_country=None,
                thumbnail_url="https://example.test/visual.jpg",
                uploaded_at=None,
            ),
        ]

    monkeypatch.setenv("CRAWLER_DISCOVERY_MODE", "hybrid")
    crawler.get_settings.cache_clear()
    monkeypatch.setattr(CrawlerService, "_crawl_search", fake_search)
    monkeypatch.setattr(CrawlerService, "_crawl_visual", fake_visual)
    service = CrawlerService(mode="real")

    results = asyncio.run(service.crawl_all("final", asset_id=UUID(asset_id)))

    assert {candidate.source_url for candidate in results} == {
        "https://example.test/shared.mp4",
        "https://example.test/visual.mp4",
    }


def test_real_mode_includes_watchlist_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_search(self, query: str, max_per_platform: int):
        return []

    async def fake_visual(self, query: str, received_asset_id):
        return []

    monkeypatch.setenv(
        "CRAWLER_WATCHLIST_URLS",
        "https://cdn.example.test/free-video.mp4, https://www.youtube.com/watch?v=abc123XYZ90",
    )
    monkeypatch.setenv("CRAWLER_DISCOVERY_MODE", "hybrid")
    crawler.get_settings.cache_clear()
    monkeypatch.setattr(CrawlerService, "_crawl_search", fake_search)
    monkeypatch.setattr(CrawlerService, "_crawl_visual", fake_visual)
    service = CrawlerService(mode="real")

    results = asyncio.run(service.crawl_all("filename title"))

    by_url = {candidate.source_url: candidate for candidate in results}
    assert set(by_url) == {
        "https://cdn.example.test/free-video.mp4",
        "https://www.youtube.com/watch?v=abc123XYZ90",
    }
    assert by_url["https://cdn.example.test/free-video.mp4"].platform == "web"
    assert by_url["https://www.youtube.com/watch?v=abc123XYZ90"].platform == "youtube"


def test_download_clip_returns_existing_file(tmp_path: Path) -> None:
    result = asyncio.run(crawler.download_clip("https://example.com/video/1", tmp_path))

    assert result.exists()
    assert result.is_file()
    assert result.parent == tmp_path


def test_download_clip_raises_without_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crawler, "SAMPLE_CLIP_PATH", tmp_path / "missing.mp4")

    with pytest.raises(CrawlerError):
        asyncio.run(crawler.download_clip("https://example.com/video/1", tmp_path))
