# app/schemas/asset.py
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl


class AssetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)


class AssetFromUrl(BaseModel):
    """Create an asset from a remote URL. Download happens async via Celery."""
    url: HttpUrl
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1024)


class AssetResponse(BaseModel):
    id: UUID
    title: str
    description: str | None
    status: str
    fingerprint_status: str
    watermark_status: str
    download_status: str
    source_url: str | None
    video_path: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AssetStatusResponse(BaseModel):
    asset_id: UUID
    status: str