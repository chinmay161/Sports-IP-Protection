# app/schemas/asset.py
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AssetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)


class AssetResponse(BaseModel):
    id: UUID
    title: str
    description: str | None
    status: str
    fingerprint_status: str
    watermark_status: str
    video_path: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssetStatusResponse(BaseModel):
    asset_id: UUID
    status: str
