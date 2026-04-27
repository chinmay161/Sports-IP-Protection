from __future__ import annotations

import asyncio
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.core.redis import redis_client
from app.db.session import get_db_session
from app.models.asset import Asset
from app.models.live_stream import LiveStream, LiveViolation
from app.schemas.live_stream import (
    LiveSegmentWatermarkRead,
    LiveStreamRead,
    LiveViolationRead,
    RegisterStreamRequest,
    SuspectUrlRequest,
    WatermarkSegmentRequest,
)
from app.services.live_stream import LiveStreamError, LiveStreamService, add_suspect_urls, count_violations


router = APIRouter()
StreamStatus = Literal["active", "ended", "suspended"]
ViolationStatus = Literal["new", "dmca_sent", "resolved"]


async def _read_stream(stream: LiveStream, db: AsyncSession) -> LiveStreamRead:
    return LiveStreamRead.model_validate(stream).model_copy(
        update={"violation_count": await count_violations(db, stream.id)}
    )


@router.post(
    "/register",
    response_model=LiveStreamRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(verify_token)],
)
async def register_stream(
    request: RegisterStreamRequest,
    db: AsyncSession = Depends(get_db_session),
) -> LiveStreamRead:
    asset = await db.get(Asset, str(request.asset_id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    try:
        stream = await LiveStreamService.register_stream(
            asset_id=request.asset_id,
            stream_key=request.stream_key,
            hls_manifest_url=request.hls_manifest_url,
            s3_prefix=request.s3_prefix,
            db=db,
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return await _read_stream(stream, db)


@router.get("", response_model=list[LiveStreamRead], dependencies=[Depends(verify_token)])
async def list_streams(
    status_filter: StreamStatus | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db_session),
) -> list[LiveStreamRead]:
    statement = select(LiveStream).order_by(LiveStream.started_at.desc())
    if status_filter is not None:
        statement = statement.where(LiveStream.status == status_filter)
    result = await db.execute(statement)
    streams = result.scalars().all()
    return [await _read_stream(stream, db) for stream in streams]


@router.get("/{stream_id}", response_model=LiveStreamRead, dependencies=[Depends(verify_token)])
async def get_stream(
    stream_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> LiveStreamRead:
    stream = await db.get(LiveStream, str(stream_id))
    if stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live stream not found")
    return await _read_stream(stream, db)


@router.post("/{stream_id}/end", dependencies=[Depends(verify_token)])
async def end_stream(
    stream_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    try:
        await LiveStreamService.end_stream(stream_id, db)
    except LiveStreamError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"stream_id": str(stream_id), "status": "ended"}


@router.post("/{stream_id}/suspect-urls", dependencies=[Depends(verify_token)])
async def add_stream_suspect_urls(
    stream_id: UUID,
    request: SuspectUrlRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    stream = await db.get(LiveStream, str(stream_id))
    if stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live stream not found")
    count = await add_suspect_urls(stream_id, request.urls)
    return {"stream_id": str(stream_id), "suspect_url_count": count}


@router.get("/{stream_id}/violations", dependencies=[Depends(verify_token)])
async def list_stream_violations(
    stream_id: UUID,
    status_filter: ViolationStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    stream = await db.get(LiveStream, str(stream_id))
    if stream is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Live stream not found")
    clauses = [LiveViolation.stream_id == str(stream_id)]
    if status_filter is not None:
        clauses.append(LiveViolation.status == status_filter)
    total_result = await db.execute(select(func.count()).select_from(LiveViolation).where(*clauses))
    rows = await db.execute(
        select(LiveViolation)
        .where(*clauses)
        .order_by(LiveViolation.detected_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return {
        "total": int(total_result.scalar_one()),
        "items": [LiveViolationRead.model_validate(row) for row in rows.scalars().all()],
    }


@router.post(
    "/{stream_id}/watermark-segment",
    response_model=LiveSegmentWatermarkRead,
    dependencies=[Depends(verify_token)],
)
async def watermark_segment(
    stream_id: UUID,
    request: WatermarkSegmentRequest,
    db: AsyncSession = Depends(get_db_session),
) -> LiveSegmentWatermarkRead:
    try:
        row = await LiveStreamService.watermark_segment(stream_id, request.segment_name, request.payload, db)
    except LiveStreamError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="No I-frame found in segment")
    return LiveSegmentWatermarkRead.model_validate(row)


@router.websocket("/ws")
async def live_streams_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("stream.registered", "stream.ended")
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
        await pubsub.unsubscribe("stream.registered", "stream.ended")
        await pubsub.aclose()
