# app/services/asset.py
import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.asset import Asset
from app.schemas.asset import AssetCreate


async def register_asset(
    db: AsyncSession,
    metadata: AssetCreate,
    file: UploadFile,
) -> Asset:
    storage_dir = Path("media_store")
    storage_dir.mkdir(parents=True, exist_ok=True)

    asset_id = str(uuid.uuid4())
    suffix = Path(file.filename).suffix if file.filename else ".mp4"
    file_path = storage_dir / f"{asset_id}{suffix}"

    with open(file_path, "wb") as buffer:
        while chunk := await file.read(1024 * 1024):
            buffer.write(chunk)

    asset = Asset(
        id=asset_id,
        title=metadata.title,
        description=metadata.description,
        status="pending",
        video_path=str(file_path),
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def get_asset(db: AsyncSession, asset_id: str) -> Asset | None:
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    return result.scalar_one_or_none()


async def list_assets(db: AsyncSession, skip: int = 0, limit: int = 20) -> list[Asset]:
    result = await db.execute(select(Asset).offset(skip).limit(limit))
    return list(result.scalars().all())