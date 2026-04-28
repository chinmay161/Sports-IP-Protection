# app/api/assets.py
import logging
import uuid
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Form, HTTPException, UploadFile, File, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import verify_token
from app.db.session import get_db_session
from app.models.asset import Asset
from app.models.watermark import WatermarkRegistry
from app.schemas.asset import AssetCreate, AssetFromUrl, AssetResponse, AssetStatusResponse
from app.schemas.watermark import (
    WatermarkRequest,
    WatermarkResult,
)
from app.services.asset import get_asset, list_assets, refresh_aggregate_status, register_asset
from app.workers.ingest_task import finalize_asset, ingest_asset
from app.workers.watermark_task import watermark_asset
from app.workers.download_task import download_asset

try:
    from celery import chord
except ImportError:  # pragma: no cover - exercised only when dependency is absent
    chord = None

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/assets",
    tags=["assets"],
    dependencies=[Depends(verify_token)],
)


def _safe_dispatch(task_callable, *args, **kwargs):
    """Dispatch a Celery task, swallowing broker errors.

    On single-container production deploys (no Celery worker, no Redis broker),
    .delay() raises a connection error. We log it and return None so the
    HTTP request can still succeed — the user gets a created resource even
    if the background task can't run.

    Returns the task id on success, None on dispatch failure.
    """
    try:
        task = task_callable.delay(*args, **kwargs)
        return task.id
    except Exception as exc:
        logger.warning(
            "celery_dispatch_failed task=%s error=%s",
            getattr(task_callable, "name", "unknown"),
            exc,
        )
        return None


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_asset(
    title: str = Form(...),
    description: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
) -> Asset:
    metadata = AssetCreate(title=title, description=description)
    return await register_asset(db=db, metadata=metadata, file=file)


@router.post("/from-url", response_model=AssetResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_asset_from_url(
    payload: AssetFromUrl,
    db: AsyncSession = Depends(get_db_session),
) -> Asset:
    """Register an asset from a remote URL. yt-dlp downloads in the background.

    Flow:
      1. Creates an Asset row with download_status='pending', video_path=''
      2. Dispatches download_asset Celery task (best effort)
      3. Task downloads -> updates video_path + download_status='ready'
      4. Task chains into ingest_asset (fingerprinting)
      5. Each transition publishes asset.status_changed to Redis

    If no Celery broker is available (single-container deploy), the asset row
    is still created with download_status='pending'. Operator can re-trigger
    via /assets/{id}/ingest once a worker is online.
    """
    asset_id = str(uuid.uuid4())

    asset = Asset(
        id=asset_id,
        title=payload.title,
        description=payload.description,
        status="processing",
        fingerprint_status="pending",
        watermark_status="ready",  # not watermarking URL-ingested assets yet
        download_status="pending",
        source_url=str(payload.url),
        video_path="",  # filled in by the download task
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)

    _safe_dispatch(download_asset, asset_id=asset_id, url=str(payload.url))
    return asset


@router.get("", response_model=list[AssetResponse])
async def list_all_assets(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db_session),
) -> list[Asset]:
    return await list_assets(db=db, skip=skip, limit=limit)


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_single_asset(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Asset:
    asset = await get_asset(db=db, asset_id=str(asset_id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


@router.post("/{asset_id}/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_asset_endpoint(
    asset_id: UUID,
    watermark: WatermarkRequest | None = Body(default=None),
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    asset = await get_asset(db=db, asset_id=str(asset_id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if asset.status not in ("pending", "failed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Asset is already {asset.status}",
        )
    asset.fingerprint_status = "processing"
    if watermark is not None:
        asset.watermark_status = "processing"
    else:
        asset.watermark_status = "ready"
    refresh_aggregate_status(asset)
    await db.commit()

    task_id: str | None = None
    if watermark is not None and chord is not None:
        try:
            task = chord(
                [
                    ingest_asset.s(str(asset_id), asset.video_path),
                    watermark_asset.s(str(asset_id), watermark.payload, watermark.alpha),
                ],
                finalize_asset.s(str(asset_id)),
            )()
            task_id = task.id
        except Exception as exc:
            logger.warning("celery_chord_dispatch_failed asset_id=%s error=%s", asset_id, exc)
    else:
        task_id = _safe_dispatch(ingest_asset, asset_id=str(asset_id), video_path=asset.video_path)

    return {"task_id": task_id or "no-broker", "status": "processing"}


@router.get("/{asset_id}/status", response_model=AssetStatusResponse)
async def get_asset_status(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    asset = await get_asset(db=db, asset_id=str(asset_id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return {"asset_id": str(asset.id), "status": asset.status}


@router.post("/{asset_id}/watermark", status_code=status.HTTP_202_ACCEPTED)
async def watermark_asset_endpoint(
    asset_id: UUID,
    request: WatermarkRequest,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    asset = await get_asset(db=db, asset_id=str(asset_id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    if asset.watermark_status == "processing":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Watermark already processing")
    asset.watermark_status = "processing"
    refresh_aggregate_status(asset)
    await db.commit()

    task_id = _safe_dispatch(
        watermark_asset,
        asset_id=str(asset_id),
        payload=request.payload,
        alpha=request.alpha,
    )
    return {"task_id": task_id or "no-broker", "status": "processing"}


@router.get("/{asset_id}/watermark", response_model=WatermarkResult)
async def get_asset_watermark(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> WatermarkResult:
    result = await db.execute(select(WatermarkRegistry).where(WatermarkRegistry.asset_id == str(asset_id)))
    registry = result.scalar_one_or_none()
    if registry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Watermark not found")
    return WatermarkResult(
        asset_id=asset_id,
        payload=registry.payload,
        keyframe_count=registry.keyframe_count,
        s3_key=f"watermarked/{asset_id}/video.mp4",
        psnr_mean=registry.psnr_mean,
    )