# backend/seed_matches.py
"""Demo data: insert synthetic Match rows for an existing asset.

Use when the matcher pipeline isn't producing real matches but you need
data downstream (propagation page, detections list, etc.).

Usage:
    python seed_matches.py <asset_id> [count]
"""
import asyncio
import random
import sys
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.db.session import SessionLocal
from app.models.asset import Asset
from app.models.match import Match


PLATFORMS = ["youtube", "tiktok", "telegram", "web"]
SEVERITIES = ["critical", "high", "medium", "low"]
COUNTRIES = ["US", "IN", "GB", "DE", "BR", "JP", "RU", "CA", "AU", None]
CHANNELS = {
    "youtube": ["SportzHighlights", "GoalZoneTV", "MatchReplayHub", "ArenaClips"],
    "tiktok":  ["@viralclips_in", "@goalszone", "@sportsfeed"],
    "telegram": ["LeakedSportsHQ", "MatchReplays", "FootyLeaks"],
    "web":     ["highlights-blog.example", "stream-mirror.example"],
}


async def main(asset_id: str, count: int = 12):
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
            confidence = round(random.uniform(0.55, 0.99), 3)
            severity = "critical" if confidence > 0.92 else "high" if confidence > 0.85 else "medium" if confidence > 0.7 else "low"

            if platform == "youtube":
                source_url = f"https://www.youtube.com/watch?v={uuid4().hex[:11]}"
            elif platform == "tiktok":
                source_url = f"https://www.tiktok.com/{channel}/video/{random.randint(10**18, 10**19 - 1)}"
            elif platform == "telegram":
                source_url = f"https://t.me/{channel}/{random.randint(100, 9999)}"
            else:
                source_url = f"https://{channel}/watch/{uuid4().hex[:8]}"

            m = Match(
                id=str(uuid4()),
                asset_id=asset_id,
                source_url=source_url,
                platform=platform,
                confidence=confidence,
                match_type="fingerprint",
                severity=severity,
                watermark_payload=None,
                source_channel=channel,
                view_count=random.randint(500, 500_000),
                duration_matched_ms=random.randint(15_000, 600_000),
                status="new",
                geo_country=random.choice(COUNTRIES),
                detected_at=now - timedelta(minutes=random.randint(0, 720)),
            )
            session.add(m)
            rows_created += 1

        await session.commit()
        print(f"Created {rows_created} Match rows for asset {asset_id}")


if __name__ == "__main__":
    asset_id = sys.argv[1] if len(sys.argv) > 1 else "aa7293bb-5848-4602-b321-c70d3f197ba6"
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 12
    asyncio.run(main(asset_id, count))