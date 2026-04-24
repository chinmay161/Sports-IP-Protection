import asyncio
import hashlib
import os
import random
import shutil
import string
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np


class CrawlerError(Exception):
    pass


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

ISO_COUNTRIES = [
    "AD", "AE", "AF", "AG", "AI", "AL", "AM", "AO", "AQ", "AR", "AS", "AT", "AU", "AW",
    "AX", "AZ", "BA", "BB", "BD", "BE", "BF", "BG", "BH", "BI", "BJ", "BL", "BM", "BN",
    "BO", "BQ", "BR", "BS", "BT", "BV", "BW", "BY", "BZ", "CA", "CC", "CD", "CF", "CG",
    "CH", "CI", "CK", "CL", "CM", "CN", "CO", "CR", "CU", "CV", "CW", "CX", "CY", "CZ",
    "DE", "DJ", "DK", "DM", "DO", "DZ", "EC", "EE", "EG", "EH", "ER", "ES", "ET", "FI",
    "FJ", "FK", "FM", "FO", "FR", "GA", "GB", "GD", "GE", "GF", "GG", "GH", "GI", "GL",
    "GM", "GN", "GP", "GQ", "GR", "GS", "GT", "GU", "GW", "GY", "HK", "HM", "HN", "HR",
    "HT", "HU", "ID", "IE", "IL", "IM", "IN", "IO", "IQ", "IR", "IS", "IT", "JE", "JM",
    "JO", "JP", "KE", "KG", "KH", "KI", "KM", "KN", "KP", "KR", "KW", "KY", "KZ", "LA",
    "LB", "LC", "LI", "LK", "LR", "LS", "LT", "LU", "LV", "LY", "MA", "MC", "MD", "ME",
    "MF", "MG", "MH", "MK", "ML", "MM", "MN", "MO", "MP", "MQ", "MR", "MS", "MT", "MU",
    "MV", "MW", "MX", "MY", "MZ", "NA", "NC", "NE", "NF", "NG", "NI", "NL", "NO", "NP",
    "NR", "NU", "NZ", "OM", "PA", "PE", "PF", "PG", "PH", "PK", "PL", "PM", "PN", "PR",
    "PS", "PT", "PW", "PY", "QA", "RE", "RO", "RS", "RU", "RW", "SA", "SB", "SC", "SD",
    "SE", "SG", "SH", "SI", "SJ", "SK", "SL", "SM", "SN", "SO", "SR", "SS", "ST", "SV",
    "SX", "SY", "SZ", "TC", "TD", "TF", "TG", "TH", "TJ", "TK", "TL", "TM", "TN", "TO",
    "TR", "TT", "TV", "TW", "TZ", "UA", "UG", "UM", "US", "UY", "UZ", "VA", "VC", "VE",
    "VG", "VI", "VN", "VU", "WF", "WS", "YE", "YT", "ZA", "ZM", "ZW",
]


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
    countries = ["US", "GB", "IN", "BR", "DE", "NG", "PH", "ID"]
    weights = [0.25, 0.12, 0.15, 0.10, 0.08, 0.08, 0.10, 0.12]

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
                    geo_country=random.choices(self.countries, weights=self.weights, k=1)[0],
                    thumbnail_url=f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
                    uploaded_at=_uploaded_at(),
                )
            )
        return results


class TikTokMockAdapter:
    countries = ["IN", "US", "PH", "BR", "ID"]
    weights = [0.34, 0.24, 0.18, 0.12, 0.12]

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
                    geo_country=random.choices(self.countries, weights=self.weights, k=1)[0],
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
    countries = ["RU", "UA", "IR", "PK", "BD"]
    weights = [0.28, 0.16, 0.18, 0.20, 0.18]

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
                    geo_country=random.choices(self.countries, weights=self.weights, k=1)[0],
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
                    geo_country=random.choice(ISO_COUNTRIES),
                    thumbnail_url=None,
                    uploaded_at=_uploaded_at(),
                )
            )
        return results


class CrawlerService:
    def __init__(self) -> None:
        self.adapters = {
            "youtube": YouTubeMockAdapter(),
            "tiktok": TikTokMockAdapter(),
            "telegram": TelegramMockAdapter(),
            "web": WebMockAdapter(),
        }

    async def crawl(self, platform: str, query: str, max_results: int = 20) -> list[CandidateVideo]:
        del query
        adapter = self.adapters.get(platform)
        if adapter is None:
            raise CrawlerError(f"Unsupported platform: {platform}")
        await asyncio.sleep(random.uniform(0.05, 0.15))
        return adapter.generate(max_results)

    async def crawl_all(self, query: str, max_per_platform: int = 20) -> list[CandidateVideo]:
        result_groups = await asyncio.gather(
            *(self.crawl(platform, query, max_per_platform) for platform in self.adapters)
        )
        by_url: dict[str, CandidateVideo] = {}
        for candidate in [item for group in result_groups for item in group]:
            by_url.setdefault(candidate.source_url, candidate)
        results = list(by_url.values())
        random.shuffle(results)
        return results

    async def download_clip(self, url: str, dest_dir: Path) -> Path:
        if os.getenv("ALLOW_REAL_CRAWL") == "1":
            raise RuntimeError("Real crawling not enabled in this build")
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


async def crawl_all(query: str, max_per_platform: int = 20) -> list[CandidateVideo]:
    return await _default_service.crawl_all(query, max_per_platform)


async def download_clip(url: str, dest_dir: Path) -> Path:
    return await _default_service.download_clip(url, dest_dir)
