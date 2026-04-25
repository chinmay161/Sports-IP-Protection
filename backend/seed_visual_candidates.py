# backend/seed_visual_candidates.py
"""Demo data: insert synthetic VisualCandidate rows for an existing asset.

Use when the visual discovery crawler isn't producing real candidates but you
need data for the frontend lookalike gallery.

Usage:
    python seed_visual_candidates.py <asset_id> [count]
"""
import asyncio
import random
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.db.session import SessionLocal
from app.models.asset import Asset
from app.models.visual import VisualCandidate


# Real-looking thumbnail URLs (placeholder generators — won't actually load
# but look plausible). Replace with real CDN URLs if you want to demo with
# actual images.
THUMBNAIL_HOSTS = [
    "https://i.ytimg.com/vi/{slug}/hqdefault.jpg",
    "https://p16-sign-va.tiktokcdn.com/{slug}.webp",
    "https://cdn.telegram.org/file/{slug}.jpg",
    "https://placehold.co/480x270/0f172a/cbd5e1?text={slug}",
]

PLATFORMS = ["youtube", "tiktok", "telegram", "web"]

CHANNELS = {
    "youtube":  ["SportzHighlights", "GoalZoneTV", "MatchReplayHub", "ArenaClips", "FastFootballEdits"],
    "tiktok":   ["@viralclips_in", "@goalszone", "@sportsfeed", "@cricketleaks"],
    "telegram": ["LeakedSportsHQ", "MatchReplays", "FootyLeaks", "CricketStreams"],
    "web":      ["highlights-blog.example", "stream-mirror.example", "fan-recap.example"],
}


def random_source_url(platform, channel):
    if platform == "youtube":
        return f"https://www.youtube.com/watch?v={uuid4().hex[:11]}"
    if platform == "tiktok":
        return f"https://www.tiktok.com/{channel}/video/{random.randint(10**18, 10**19 - 1)}"
    if platform == "telegram":
        return f"https://t.me/{channel}/{random.randint(100, 9999)}"
    return f"https://{channel}/watch/{uuid4().hex[:8]}"


def random_page_url(source_url):
    # For most platforms, page_url == source_url. Sometimes it's the parent.
    if random.random() < 0.7:
        return source_url
    parts = source_url.rsplit("/", 1)
    return parts[0] if len(parts) == 2 else source_url


def random_thumbnail_url():
    template = random.choice(THUMBNAIL_HOSTS)
    return template.format(slug=uuid4().hex[:11])


async def main(asset_id: str, count: int = 10):
    async with SessionLocal() as session:
        asset = await session.get(Asset, asset_id)
        if asset is None:
            print(f"Asset {asset_id} not found")
            return

        now = datetime.now(UTC)
        rows_created = 0
        for i in range(count):
            platform = random.choice(PLATFORMS)
            channel = random.choice(CHANNELS[platform])
            source_url = random_source_url(platform, channel)

            # phash distance: 1-18 (matches your VISUAL_PHASH_THRESHOLD=18)
            # Lower = more similar. We weight toward "very similar" for drama.
            phash_distance = random.choice([2, 3, 4, 5, 6, 7, 8, 9, 11, 14, 16])

            # CLIP score: -1 to 1, but we keep it 0.5-0.95 (typical for similar imagery).
            # 30% of rows have None (CLIP unavailable on candidate side).
            clip_score = None if random.random() < 0.3 else round(random.uniform(0.55, 0.94), 4)

            # Visual score follows the service's actual formula
            phash_score = max(0.0, 1.0 - (phash_distance / 18))
            if clip_score is None:
                visual_score = round(phash_score, 4)
            else:
                normalized_clip = max(0.0, min(1.0, (clip_score + 1.0) / 2.0))
                visual_score = round((phash_score * 0.65) + (normalized_clip * 0.35), 4)

            row = VisualCandidate(
                id=str(uuid4()),
                asset_id=asset_id,
                source_url=source_url,
                page_url=random_page_url(source_url),
                platform=platform,
                thumbnail_url=random_thumbnail_url(),
                phash_distance=phash_distance,
                clip_score=clip_score,
                visual_score=visual_score,
                discovered_at=now - timedelta(minutes=random.randint(0, 360)),
            )
            session.add(row)
            rows_created += 1

        await session.commit()
        print(f"Created {rows_created} VisualCandidate rows for asset {asset_id}")


if __name__ == "__main__":
    asset_id = sys.argv[1] if len(sys.argv) > 1 else "0c94be8e-fd8d-418c-9e78-2104b3d7e3aa"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    asyncio.run(main(asset_id, count))