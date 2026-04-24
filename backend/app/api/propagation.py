from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.db.session import get_db_session
from app.models.asset import Asset
from app.models.match import Match

router = APIRouter(
    prefix="/propagation",
    tags=["propagation"],
    dependencies=[Depends(verify_token)],
)

BUCKET_SIZE_MS = 3_600_000


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _node(match: Match, origin_id: str) -> dict[str, object]:
    return {
        "id": match.id,
        "type": "origin" if match.id == origin_id else "repost",
        "platform": match.platform,
        "channel": match.source_channel,
        "url": match.source_url,
        "view_count": match.view_count,
        "confidence": match.confidence,
        "severity": match.severity,
        "geo_country": match.geo_country,
        "detected_at": _utc_iso(match.detected_at),
        "status": match.status,
    }


def _edge(previous: Match, current: Match, index: int) -> dict[str, object]:
    delta = int((current.detected_at - previous.detected_at).total_seconds() * 1000)
    return {
        "id": f"e{index:03d}",
        "source": previous.id,
        "target": current.id,
        "relation": "repost",
        "delta_ms": max(0, delta),
    }


async def _matches_for_match(match_id: UUID, db: AsyncSession) -> tuple[Match, list[Match]]:
    origin = await db.get(Match, str(match_id))
    if origin is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Match not found")

    result = await db.execute(
        select(Match)
        .where(Match.asset_id == origin.asset_id)
        .order_by(Match.detected_at.asc(), Match.id.asc())
    )
    return origin, list(result.scalars().all())


@router.get("/{match_id}/graph")
async def propagation_graph(
    match_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    origin, matches = await _matches_for_match(match_id, db)
    nodes = [_node(match, origin.id) for match in matches]
    edges = [
        _edge(previous, current, index)
        for index, (previous, current) in enumerate(zip(matches, matches[1:]), start=1)
    ]
    platform_spread = Counter(match.platform for match in matches)
    first_detected_at = matches[0].detected_at if matches else None
    last_detected_at = matches[-1].detected_at if matches else None
    spread_duration_ms = 0
    if first_detected_at is not None and last_detected_at is not None:
        spread_duration_ms = int((last_detected_at - first_detected_at).total_seconds() * 1000)

    return {
        "match_id": str(match_id),
        "generated_at": _utc_iso(datetime.now(UTC)),
        "nodes": nodes,
        "edges": edges,
        "meta": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "platform_spread": dict(platform_spread),
            "first_detected_at": _utc_iso(first_detected_at),
            "spread_duration_ms": spread_duration_ms,
            "origin_country": origin.geo_country,
        },
    }


@router.get("/{match_id}/timeline")
async def propagation_timeline(
    match_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    _, matches = await _matches_for_match(match_id, db)
    if not matches:
        return {
            "match_id": str(match_id),
            "bucket_size_ms": BUCKET_SIZE_MS,
            "buckets": [],
            "peak_bucket": None,
            "velocity_index": 0.0,
        }

    buckets: dict[datetime, list[Match]] = {}
    for match in matches:
        bucket_start = match.detected_at.replace(minute=0, second=0, microsecond=0)
        buckets.setdefault(bucket_start, []).append(match)

    cumulative_nodes = 0
    cumulative_views = 0
    payload_buckets = []
    peak_bucket = None
    peak_new_nodes = 0
    for bucket_start in sorted(buckets):
        group = buckets[bucket_start]
        cumulative_nodes += len(group)
        cumulative_views += sum(match.view_count or 0 for match in group)
        if len(group) > peak_new_nodes:
            peak_new_nodes = len(group)
            peak_bucket = bucket_start
        payload_buckets.append(
            {
                "bucket_start": _utc_iso(bucket_start),
                "new_nodes": len(group),
                "cumulative_nodes": cumulative_nodes,
                "cumulative_views": cumulative_views,
            }
        )

    return {
        "match_id": str(match_id),
        "bucket_size_ms": BUCKET_SIZE_MS,
        "buckets": payload_buckets,
        "peak_bucket": _utc_iso(peak_bucket),
        "velocity_index": round(peak_new_nodes / max(1, len(payload_buckets)), 2),
    }


@router.get("/{asset_id}/summary")
async def propagation_summary(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    asset = await db.get(Asset, str(asset_id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    result = await db.execute(
        select(Match)
        .where(Match.asset_id == str(asset_id))
        .order_by(Match.detected_at.asc(), Match.id.asc())
    )
    matches = list(result.scalars().all())
    if not matches:
        return {
            "asset_id": str(asset_id),
            "total_infringing_copies": 0,
            "total_estimated_views": 0,
            "platforms_reached": [],
            "countries_reached": 0,
            "fastest_repost_ms": None,
            "origin_platform": None,
            "peak_velocity_index": 0.0,
        }

    deltas = [
        int((current.detected_at - previous.detected_at).total_seconds() * 1000)
        for previous, current in zip(matches, matches[1:])
    ]
    by_hour = Counter(match.detected_at.replace(minute=0, second=0, microsecond=0) for match in matches)

    return {
        "asset_id": str(asset_id),
        "total_infringing_copies": len(matches),
        "total_estimated_views": sum(match.view_count or 0 for match in matches),
        "platforms_reached": sorted({match.platform for match in matches}),
        "countries_reached": len({match.geo_country for match in matches if match.geo_country}),
        "fastest_repost_ms": min(deltas) if deltas else None,
        "origin_platform": matches[0].platform,
        "peak_velocity_index": float(max(by_hour.values(), default=0)),
    }
