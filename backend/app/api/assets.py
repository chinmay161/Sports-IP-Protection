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

