import asyncio
import hashlib
import inspect
import logging
import random
import shutil
import string
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from uuid import UUID

import httpx
import numpy as np

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.geoip import country_for_url

try:
    from yt_dlp import YoutubeDL
except ImportError:  # pragma: no cover - exercised only when optional runtime dep is absent
    YoutubeDL = None


class CrawlerError(Exception):
    pass


class RealCrawlerUnavailable(CrawlerError):
    pass


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class CandidateVideo:
    source_url: str
    platform: str
    channel: str | None
    view_count: int | None
    duration_ms: int | None
    geo_country: str | None
    thumbnail_url: str | None
    uploaded_at: datetime | None


BACKEND_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_CLIP_PATH = BACKEND_ROOT / "media_store" / "ea1e3a18-b6bd-49dd-b958-78736560f24f.mp4"

def _random_alnum(length: int) -> str:
    return "".join(random.choices(string.ascii_letters + string.digits, k=length))


def _slug() -> str:
    words = ["match", "final", "replay", "goal", "highlights", "full", "clip", "stream"]
    return "-".join(random.choices(words, k=random.randint(3, 5))) + f"-{random.randint(100, 9999)}"


def _uploaded_at(max_days: int = 30) -> datetime:
    return datetime.now(UTC) - timedelta(days=random.randint(0, max_days))


class YouTubeMockAdapter:
    channels = [
        "SportzHighlights", "GoalZoneTV", "MatchReplayHub", "ArenaClips", "PremierPlays",
        "FullTimeFocus", "SidelineReels", "FastBreakDaily", "CricketPulse", "RugbyVault",
        "HoopsCentral", "KickoffNation", "TrophyTrail", "LiveSportCuts", "ExtraTimeNow",
        "StadiumStories", "VolleyVision", "FightNightRecap", "RaceDayClips", "GridironLoop",
    ]
    def generate(self, max_results: int) -> list[CandidateVideo]:
        results = []
        for _ in range(max_results):
            video_id = _random_alnum(11)
            view_count = min(int(np.random.pareto(2) * 1000), 2_000_000)
            results.append(
                CandidateVideo(
                    source_url=f"https://www.youtube.com/watch?v={video_id}",
                    platform="youtube",
                    channel=random.choice(self.channels),
                    view_count=view_count,
                    duration_ms=random.randint(30_000, 600_000),
                    geo_country=None,
                    thumbnail_url=f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
                    uploaded_at=_uploaded_at(),
                )
            )
        return results


class TikTokMockAdapter:
    def generate(self, max_results: int) -> list[CandidateVideo]:
        results = []
        for _ in range(max_results):
            user = f"sports{_random_alnum(6).lower()}"
            video_id = random.randint(10**18, 10**19 - 1)
            view_count = min(int(np.random.pareto(1.5) * 5000), 10_000_000)
            results.append(
                CandidateVideo(
                    source_url=f"https://www.tiktok.com/@{user}/video/{video_id}",
                    platform="tiktok",
                    channel=user,
                    view_count=view_count,
                    duration_ms=random.randint(15_000, 180_000),
                    geo_country=None,
                    thumbnail_url=f"https://p16-sign.tiktokcdn-us.com/tos-useast5/{video_id}.jpeg",
                    uploaded_at=_uploaded_at(),
                )
            )
        return results


class TelegramMockAdapter:
    channels = [
        "sports_replays", "goal_streams", "matchday_clips", "cricket_livezone", "football_vault",
        "arena_uploads", "fight_replays", "tennis_points", "basketball_digest", "rugby_streams",
    ]
    def generate(self, max_results: int) -> list[CandidateVideo]:
        results = []
        for _ in range(max_results):
            channel = random.choice(self.channels)
            post_id = random.randint(1000, 9999)
            results.append(
                CandidateVideo(
                    source_url=f"https://t.me/{channel}/{post_id}",
                    platform="telegram",
                    channel=channel,
                    view_count=random.randint(100, 50_000),
                    duration_ms=random.randint(60_000, 1_800_000),
                    geo_country=None,
                    thumbnail_url=None,
                    uploaded_at=_uploaded_at(),
                )
            )
        return results


class WebMockAdapter:
    domains = [
        "streamarena.example", "sportsmirror.example", "matchvault.example", "replayhub.example",
        "goalclips.example", "livearchive.example", "fanstream.example", "clipzone.example",
        "fullmatch.example", "sportscdn.example", "watchlocker.example", "replaycast.example",
        "stadiumfeed.example", "gamefile.example", "eventstream.example",
    ]

    def generate(self, max_results: int) -> list[CandidateVideo]:
        results = []
        for _ in range(max_results):
            subdomain = random.choice(["live", "cdn", "watch", "video", "media", "replay"])
            domain = random.choice(self.domains)
            results.append(
                CandidateVideo(
                    source_url=f"https://{subdomain}.{domain}/watch/{_slug()}",
                    platform="web",
                    channel=domain,
                    view_count=random.randint(50, 10_000),
                    duration_ms=random.randint(30_000, 900_000),
                    geo_country=None,
                    thumbnail_url=None,
                    uploaded_at=_uploaded_at(),
                )
            )
        return results


def _require_ytdlp() -> type:
    if YoutubeDL is None:
        raise RealCrawlerUnavailable(
            "Real crawling requires yt-dlp. Install backend requirements and set CRAWLER_MODE=real."
        )
    return YoutubeDL


def _parse_uploaded_at(info: dict) -> datetime | None:
    timestamp = info.get("timestamp")
    if timestamp is not None:
        try:
            return datetime.fromtimestamp(int(timestamp), UTC)
        except (TypeError, ValueError, OSError):
            pass

    upload_date = info.get("upload_date")
    if isinstance(upload_date, str) and len(upload_date) == 8:
        try:
            return datetime.strptime(upload_date, "%Y%m%d").replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def _metadata_to_candidate(info: dict, platform: str) -> CandidateVideo | None:
    source_url = info.get("webpage_url") or info.get("original_url") or info.get("url")
    if platform == "youtube" and (
        not isinstance(source_url, str) or not source_url.startswith(("http://", "https://"))
    ):
        video_id = info.get("id") or info.get("url")
        if isinstance(video_id, str) and video_id:
            source_url = f"https://www.youtube.com/watch?v={video_id}"
    if not isinstance(source_url, str) or not source_url.startswith(("http://", "https://")):
        return None

    duration = info.get("duration")
    duration_ms = int(float(duration) * 1000) if duration is not None else None
    channel = info.get("channel") or info.get("uploader") or info.get("creator")
    view_count = info.get("view_count")

    return _with_resolved_geo(
        CandidateVideo(
            source_url=source_url,
            platform=platform,
            channel=str(channel) if channel else None,
            view_count=int(view_count) if view_count is not None else None,
            duration_ms=duration_ms,
            geo_country=None,
            thumbnail_url=info.get("thumbnail") if isinstance(info.get("thumbnail"), str) else None,
            uploaded_at=_parse_uploaded_at(info),
        )
    )


def _platform_for_candidate_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "youtube." in host or "youtu.be" in host:
        return "youtube"
    if "tiktok." in host:
        return "tiktok"
    if "t.me" in host or "telegram." in host:
        return "telegram"
    return "web"


def _run_ytdlp_extract(url: str, *, flat: bool = True) -> dict:
    ydl_cls = _require_ytdlp()
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist" if flat else False,
    }
    with ydl_cls(options) as ydl:
        return ydl.extract_info(url, download=False)


def _youtube_search(query: str, max_results: int) -> list[CandidateVideo]:
    info = _run_ytdlp_extract(f"ytsearch{max_results}:{query}", flat=True)
    entries = info.get("entries") or []
    candidates: list[CandidateVideo] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        candidate = _metadata_to_candidate(entry, "youtube")
        if candidate is not None:
            candidates.append(candidate)
    return candidates[:max_results]


class DuckDuckGoResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        attr_map = dict(attrs)
        href = attr_map.get("href")
        css_class = attr_map.get("class", "")
        if not href or "result__a" not in css_class:
            return
        self.urls.append(_unwrap_duckduckgo_url(href))


def _unwrap_duckduckgo_url(url: str) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    uddg = query.get("uddg")
    if uddg:
        return unquote(uddg[0])
    return url


async def _duckduckgo_search(query: str, max_results: int) -> list[str]:
    search_url = "https://duckduckgo.com/html/?" + urlencode({"q": query})
    async with httpx.AsyncClient(
        timeout=20.0,
        follow_redirects=True,
        headers={"User-Agent": "sports-ip-protection-crawler/1.0"},
    ) as client:
        response = await client.get(search_url)
        response.raise_for_status()
    parser = DuckDuckGoResultParser()
    parser.feed(response.text)
    seen: set[str] = set()
    urls: list[str] = []
    for url in parser.urls:
        if url not in seen and url.startswith(("http://", "https://")):
            seen.add(url)
            urls.append(url)
        if len(urls) >= max_results:
            break
    return urls


class YouTubeRealAdapter:
    async def search(self, query: str, max_results: int) -> list[CandidateVideo]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, lambda: _youtube_search(query, max_results))


class SearchRealAdapter:
    def __init__(
        self,
        platform: str,
        search_prefix: str,
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        self.platform = platform
        self.search_prefix = search_prefix
        self.allowed_hosts = allowed_hosts

    async def search(self, query: str, max_results: int) -> list[CandidateVideo]:
        urls = await _duckduckgo_search(f"{self.search_prefix} {query}", max_results * 2)
        candidates: list[CandidateVideo] = []
        for url in urls:
            host = urlparse(url).netloc.lower()
            if self.allowed_hosts and not any(host.endswith(allowed) for allowed in self.allowed_hosts):
                continue
            candidates.append(
                _with_resolved_geo(
                    CandidateVideo(
                        source_url=url,
                        platform=self.platform,
                        channel=host or None,
                        view_count=None,
                        duration_ms=None,
                        geo_country=None,
                        thumbnail_url=None,
                        uploaded_at=None,
                    )
                )
            )
            if len(candidates) >= max_results:
                break
        return candidates


def _download_with_ytdlp(url: str, dest_dir: Path) -> Path:
    ydl_cls = _require_ytdlp()
    dest_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(dest_dir / "%(id)s.%(ext)s")
    options = {
        "format": "bv*+ba/best",
        "merge_output_format": "mp4",
        "outtmpl": output_template,
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    before = set(dest_dir.iterdir())
    with ydl_cls(options) as ydl:
        info = ydl.extract_info(url, download=True)

    requested = info.get("requested_downloads") or []
    for download in requested:
        filepath = download.get("filepath")
        if filepath:
            path = Path(filepath)
            if path.exists():
                return path

    after = [path for path in dest_dir.iterdir() if path not in before and path.is_file()]
    if after:
        return max(after, key=lambda path: path.stat().st_mtime)
    raise CrawlerError(f"yt-dlp did not produce a downloadable media file for {url}")


async def _download_direct_video(url: str, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(urlparse(url).path).suffix
    if suffix.lower() not in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}:
        suffix = ".mp4"
    dest_path = dest_dir / f"{hashlib.sha256(url.encode()).hexdigest()[:12]}{suffix}"
    async with httpx.AsyncClient(
        timeout=60.0,
        follow_redirects=True,
        headers={"User-Agent": "sports-ip-protection-crawler/1.0"},
    ) as client:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            if "video/" not in content_type and "application/octet-stream" not in content_type:
                raise CrawlerError(f"URL did not return a video response: {content_type or 'unknown'}")
            with dest_path.open("wb") as output:
                async for chunk in response.aiter_bytes():
                    output.write(chunk)
    return dest_path


class CrawlerService:
    def __init__(self, mode: str | None = None) -> None:
        self.mode = (mode or get_settings().crawler_mode or "mock").strip().lower()
        if self.mode not in {"mock", "real"}:
            raise CrawlerError(f"Unsupported crawler mode: {self.mode}")
        self.adapters = self._build_adapters()

    def _build_adapters(self):
        if self.mode == "real":
            return {
                "youtube": YouTubeRealAdapter(),
                "tiktok": SearchRealAdapter("tiktok", "site:tiktok.com/@ video", ("tiktok.com",)),
                "telegram": SearchRealAdapter("telegram", "site:t.me sports video", ("t.me",)),
                "web": SearchRealAdapter("web", "sports replay video"),
            }
        return {
            "youtube": YouTubeMockAdapter(),
            "tiktok": TikTokMockAdapter(),
            "telegram": TelegramMockAdapter(),
            "web": WebMockAdapter(),
        }

    async def crawl(self, platform: str, query: str, max_results: int = 20) -> list[CandidateVideo]:
        adapter = self.adapters.get(platform)
        if adapter is None:
            raise CrawlerError(f"Unsupported platform: {platform}")
        await asyncio.sleep(random.uniform(0.05, 0.15))
        if hasattr(adapter, "search"):
            search = adapter.search
            if inspect.iscoroutinefunction(search):
                return await search(query, max_results)
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, lambda: search(query, max_results))
        return [_with_resolved_geo(candidate) for candidate in adapter.generate(max_results)]

    async def crawl_all(
        self,
        query: str,
        max_per_platform: int = 20,
        asset_id: UUID | None = None,
    ) -> list[CandidateVideo]:
        if self.mode == "real":
            watchlist_results = self._crawl_watchlist_urls()
            discovery_mode = get_settings().crawler_discovery_mode
            if discovery_mode == "visual":
                visual_results = await self._crawl_visual(query, asset_id)
                return self._dedupe_and_shuffle(watchlist_results + visual_results)
            if discovery_mode == "hybrid":
                search_results, visual_results = await asyncio.gather(
                    self._crawl_search(query, max_per_platform),
                    self._crawl_visual(query, asset_id),
                )
                return self._dedupe_and_shuffle(watchlist_results + search_results + visual_results)
            if discovery_mode != "search":
                raise CrawlerError(f"Unsupported discovery mode: {discovery_mode}")
            search_results = await self._crawl_search(query, max_per_platform)
            return self._dedupe_and_shuffle(watchlist_results + search_results)
        return await self._crawl_search(query, max_per_platform)

    def _crawl_watchlist_urls(self) -> list[CandidateVideo]:
        raw_urls = get_settings().crawler_watchlist_urls or ""
        urls = [
            url.strip()
            for url in raw_urls.split(",")
            if url.strip().startswith(("http://", "https://"))
        ]
        return [
            _with_resolved_geo(
                CandidateVideo(
                    source_url=url,
                    platform=_platform_for_candidate_url(url),
                    channel=urlparse(url).netloc or None,
                    view_count=None,
                    duration_ms=None,
                    geo_country=None,
                    thumbnail_url=None,
                    uploaded_at=None,
                )
            )
            for url in urls
        ]

    async def _crawl_search(self, query: str, max_per_platform: int) -> list[CandidateVideo]:
        result_groups = await asyncio.gather(
            *(self.crawl(platform, query, max_per_platform) for platform in self.adapters)
        )
        return self._dedupe_and_shuffle([item for group in result_groups for item in group])

    async def _crawl_visual(self, query: str, asset_id: UUID | None) -> list[CandidateVideo]:
        if asset_id is None:
            return []
        try:
            from app.services.visual_discovery import VisualDiscoveryService

            async with SessionLocal() as session:
                return await VisualDiscoveryService(session).discover(asset_id=asset_id, query=query)
        except Exception as exc:
            LOGGER.warning("visual_discovery_failed asset_id=%s error=%s", asset_id, exc)
            return []

    def _dedupe_and_shuffle(self, candidates: list[CandidateVideo]) -> list[CandidateVideo]:
        by_url: dict[str, CandidateVideo] = {}
        for candidate in candidates:
            by_url.setdefault(candidate.source_url, candidate)
        results = list(by_url.values())
        random.shuffle(results)
        return results

    async def download_clip(self, url: str, dest_dir: Path) -> Path:
        if self.mode == "real":
            try:
                loop = asyncio.get_running_loop()
                return await loop.run_in_executor(None, lambda: _download_with_ytdlp(url, dest_dir))
            except RealCrawlerUnavailable:
                return await _download_direct_video(url, dest_dir)
        if not SAMPLE_CLIP_PATH.exists():
            raise CrawlerError(f"Sample clip fixture missing: {SAMPLE_CLIP_PATH}")
        dest_dir.mkdir(parents=True, exist_ok=True)
        clip_name = f"{hashlib.sha256(url.encode()).hexdigest()[:12]}.mp4"
        dest_path = dest_dir / clip_name
        shutil.copyfile(SAMPLE_CLIP_PATH, dest_path)
        await asyncio.sleep(random.uniform(0.05, 0.2))
        return dest_path


_default_service = CrawlerService()


async def crawl(platform: str, query: str, max_results: int = 20) -> list[CandidateVideo]:
    return await _default_service.crawl(platform, query, max_results)


async def crawl_all(
    query: str,
    max_per_platform: int = 20,
    asset_id: UUID | None = None,
) -> list[CandidateVideo]:
    return await _default_service.crawl_all(query, max_per_platform, asset_id=asset_id)


async def download_clip(url: str, dest_dir: Path) -> Path:
    return await _default_service.download_clip(url, dest_dir)


def _with_resolved_geo(candidate: CandidateVideo) -> CandidateVideo:
    if candidate.geo_country is not None:
        return candidate
    geo_country = country_for_url(candidate.source_url)
    if geo_country is None:
        return candidate
    return CandidateVideo(
        source_url=candidate.source_url,
        platform=candidate.platform,
        channel=candidate.channel,
        view_count=candidate.view_count,
        duration_ms=candidate.duration_ms,
        geo_country=geo_country,
        thumbnail_url=candidate.thumbnail_url,
        uploaded_at=candidate.uploaded_at,
    )
