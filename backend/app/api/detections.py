from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.auth import verify_token
from app.core.config import get_settings
from app.core.redis import redis_client
from app.db.session import get_db_session
from app.models.asset import Asset
from app.models.match import Match, MatchNote
from app.schemas.match import (
    AcknowledgeRequest,
    DmcaResponse,
    EvidenceResponse,
    MatchRead,
    ScanRequest,
    ScanResponse,
    StatsResponse,
)
from app.schemas.watermark import WatermarkDetection, WatermarkScanRequest
from app.services.evidence import EvidenceError, get_download_url as evidence_download_url
from app.services.watermark import WatermarkService, decode_watermark_key
from app.workers.evidence_task import generate as evidence_generate
from app.workers.scan_task import scan_asset

router = APIRouter()

Platform = Literal["youtube", "tiktok", "telegram", "web", "unknown"]
Severity = Literal["low", "medium", "high", "critical"]
MatchStatus = Literal["new", "alerted", "acknowledged", "dmca_sent", "resolved"]

PLATFORMS = ("youtube", "tiktok", "telegram", "web", "unknown")
SEVERITIES = ("critical", "high", "medium", "low")
STATUSES = ("new", "alerted", "acknowledged", "dmca_sent", "resolved")


def _filters(
    asset_id: UUID | None,
    platform: str | None,
    severity: str | None,
    match_status: str | None,
) -> list[object]:
    clauses: list[object] = []
    if asset_id is not None:
        clauses.append(Match.asset_id == str(asset_id))
    if platform is not None:
        clauses.append(Match.platform == platform)
    if severity is not None:
        clauses.append(Match.severity == severity)
    if match_status is not None:
        clauses.append(Match.status == match_status)
    return clauses


@router.get("", dependencies=[Depends(verify_token)])
async def list_detections(
    asset_id: UUID | None = None,
    platform: Platform | None = None,
    severity: Severity | None = None,
    match_status: MatchStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    clauses = _filters(asset_id, platform, severity, match_status)
    total_count = select(func.count().label("total")).select_from(Match).where(*clauses).subquery()
    page_ids = (
        select(Match.id)
        .where(*clauses)
        .order_by(Match.detected_at.desc())
        .limit(limit)
        .offset(offset)
        .subquery()
    )
    statement = (
        select(Match, total_count.c.total)
        .select_from(total_count)
        .outerjoin(page_ids, true())
        .outerjoin(Match, Match.id == page_ids.c.id)
        .options(selectinload(Match.segments))
        .order_by(Match.detected_at.desc())
    )
    result = await db.execute(statement)
    rows = result.all()
    total = rows[0].total if rows else 0
    return {
        "total": total,
        "items": [MatchRead.model_validate(row.Match) for row in rows if row.Match is not None],
    }


@router.get("/stats", response_model=StatsResponse, dependencies=[Depends(verify_token)])
async def detection_stats(db: AsyncSession = Depends(get_db_session)) -> StatsResponse:
    total_result = await db.execute(select(func.count()).select_from(Match))
    severity_result = await db.execute(select(Match.severity, func.count()).group_by(Match.severity))
    platform_result = await db.execute(select(Match.platform, func.count()).group_by(Match.platform))
    status_result = await db.execute(select(Match.status, func.count()).group_by(Match.status))
    country_result = await db.execute(
        select(Match.geo_country, func.count().label("count"))
        .where(Match.geo_country.is_not(None))
        .group_by(Match.geo_country)
        .order_by(func.count().desc())
        .limit(10)
    )

    severity_counts = dict(severity_result.all())
    platform_counts = dict(platform_result.all())
    status_counts = dict(status_result.all())

    return StatsResponse(
        total_matches=total_result.scalar_one(),
        by_severity={key: int(severity_counts.get(key, 0)) for key in SEVERITIES},
        by_platform={key: int(platform_counts.get(key, 0)) for key in PLATFORMS},
        by_status={key: int(status_counts.get(key, 0)) for key in STATUSES},
        top_infringing_countries=[
            {"country": country, "count": int(count)} for country, count in country_result.all()
        ],
    )


@router.post("/scan", response_model=ScanResponse, dependencies=[Depends(verify_token)])
async def scan_detection_asset(
    request: ScanRequest,
    db: AsyncSession = Depends(get_db_session),
) -> ScanResponse:
    asset = await db.get(Asset, str(request.asset_id))
    if asset is None or asset.status != "ready":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    task = scan_asset.delay(str(request.asset_id), request.max_per_platform)
    return ScanResponse(task_id=task.id, status="queued")


@router.post("/watermark-scan", dependencies=[Depends(verify_token)])
async def watermark_scan_endpoint(request: WatermarkScanRequest) -> WatermarkDetection | dict[str, bool]:
    settings = get_settings()
    if not settings.watermark_secret_key:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Watermark key not configured")
    try:
        key = decode_watermark_key(settings.watermark_secret_key)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Invalid watermark key") from exc
    detection = await WatermarkService().detect_from_url(request.url, key)
    if detection is None:
        return {"matched": False}
    return detection


@router.get("/{match_id}", response_model=MatchRead, dependencies=[Depends(verify_token)])
async def get_detection(
    match_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Match:
    result = await db.execute(
        select(Match)
        .options(selectinload(Match.segments))
        .where(Match.id == str(match_id))
    )
    match = result.scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detection not found")
    return match


@router.post("/{match_id}/acknowledge", response_model=MatchRead, dependencies=[Depends(verify_token)])
async def acknowledge_detection(
    match_id: UUID,
    request: AcknowledgeRequest,
    db: AsyncSession = Depends(get_db_session),
) -> Match:
    result = await db.execute(
        select(Match)
        .options(selectinload(Match.segments))
        .where(Match.id == str(match_id))
    )
    match = result.scalar_one_or_none()
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detection not found")
    if match.status in {"dmca_sent", "resolved"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot acknowledge a {match.status} detection",
        )

    match.status = "acknowledged"
    match.alerted_at = datetime.now(UTC)
    db.add(MatchNote(match_id=str(match_id), note=request.note or ""))
    await db.commit()
    await db.refresh(match)
    return match


@router.post("/{match_id}/dmca", response_model=DmcaResponse, dependencies=[Depends(verify_token)])
async def dmca_detection(
    match_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> DmcaResponse:
    match = await db.get(Match, str(match_id))
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detection not found")
    if match.status == "resolved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot send DMCA for a resolved detection",
        )

    match.status = "dmca_sent"
    await db.commit()
    task = evidence_generate.delay(str(match_id))
    return DmcaResponse(match_id=match_id, status="dmca_sent", task_id=task.id)


@router.get("/{match_id}/evidence", dependencies=[Depends(verify_token)])
async def get_evidence_package(
    match_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> EvidenceResponse | dict[str, str]:
    match = await db.get(Match, str(match_id))
    if match is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Detection not found")
    try:
        payload = await evidence_download_url(str(match_id), db)
        return EvidenceResponse(**payload)
    except EvidenceError as exc:
        if match.status == "dmca_sent":
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content={"status": "generating"})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.websocket("/ws")
async def detections_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("match.created")
    last_ping = asyncio.get_running_loop().time()
    try:
        while True:
            try:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                    timeout=1.5,
                )
            except asyncio.TimeoutError:
                message = None

            if message and message.get("type") == "message":
                raw = message.get("data")
                try:
                    await websocket.send_json(json.loads(raw))
                except (TypeError, json.JSONDecodeError):
                    await websocket.send_text(str(raw))

            now = asyncio.get_running_loop().time()
            if now - last_ping >= 30:
                await websocket.send_json({"type": "ping"})
                last_ping = now
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe("match.created")
        await pubsub.aclose()
