import asyncio
import re
from pathlib import Path

import pytest

from app.services import crawler
from app.services.crawler import CrawlerError, TikTokMockAdapter, YouTubeMockAdapter


def test_youtube_platform_and_url_format() -> None:
    results = asyncio.run(crawler.crawl("youtube", "test", 10))

    assert all(candidate.platform == "youtube" for candidate in results)
    assert all(
        re.match(r"^https://www\.youtube\.com/watch\?v=[A-Za-z0-9]{11}$", candidate.source_url)
        for candidate in results
    )


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


def test_download_clip_returns_existing_file(tmp_path: Path) -> None:
    result = asyncio.run(crawler.download_clip("https://example.com/video/1", tmp_path))

    assert result.exists()
    assert result.is_file()
    assert result.parent == tmp_path


def test_download_clip_raises_without_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crawler, "SAMPLE_CLIP_PATH", tmp_path / "missing.mp4")

    with pytest.raises(CrawlerError):
        asyncio.run(crawler.download_clip("https://example.com/video/1", tmp_path))
