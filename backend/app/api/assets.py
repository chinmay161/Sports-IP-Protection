'''

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.asset import Asset
from app.workers.ingest_task import ingest_asset


router = APIRouter(prefix="/assets", tags=["assets"])


@router.post("/{asset_id}/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_asset_endpoint(
    asset_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    asset = await session.get(Asset, str(asset_id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    if asset.status != "processing":
        asset.status = "processing"
        await session.commit()

    task = ingest_asset.delay(asset_id=str(asset_id), video_path=asset.video_path)
    return {"task_id": task.id, "status": "processing"}


@router.get("/{asset_id}/status")
async def get_asset_status(
    asset_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    statement = select(Asset).where(Asset.id == str(asset_id))
    result = await session.execute(statement)
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return {"asset_id": asset.id, "status": asset.status}

'''

# app/api/assets.py
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, File, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db_session
from app.models.asset import Asset
from app.schemas.asset import AssetCreate, AssetResponse, AssetStatusResponse
from app.services.asset import get_asset, list_assets, register_asset
from app.workers.ingest_task import ingest_asset


router = APIRouter(prefix="/assets", tags=["assets"])


@router.post("", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def create_asset(
    title: str = Form(...),
    description: str | None = Form(default=None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db_session),
) -> Asset:
    """Register a new digital asset and upload its media file."""
    metadata = AssetCreate(title=title, description=description)
    return await register_asset(db=db, metadata=metadata, file=file)


@router.get("", response_model=list[AssetResponse])
async def list_all_assets(
    skip: int = 0,
    limit: int = 20,
    db: AsyncSession = Depends(get_db_session),
) -> list[Asset]:
    """Return all registered assets."""
    return await list_assets(db=db, skip=skip, limit=limit)


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_single_asset(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> Asset:
    """Fetch a single asset by ID."""
    asset = await get_asset(db=db, asset_id=str(asset_id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return asset


@router.post("/{asset_id}/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_asset_endpoint(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Trigger background fingerprint generation for an asset."""
    asset = await get_asset(db=db, asset_id=str(asset_id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    if asset.status not in ("pending", "failed"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Asset is already {asset.status}",
        )

    asset.status = "processing"
    await db.commit()

    task = ingest_asset.delay(asset_id=str(asset_id), video_path=asset.video_path)
    return {"task_id": task.id, "status": "processing"}


@router.get("/{asset_id}/status", response_model=AssetStatusResponse)
async def get_asset_status(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db_session),
) -> dict[str, str]:
    """Get current processing status of an asset."""
    asset = await get_asset(db=db, asset_id=str(asset_id))
    if asset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")
    return {"asset_id": str(asset.id), "status": asset.status}