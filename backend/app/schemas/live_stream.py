from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class LiveStreamRead(BaseModel):
    id: UUID
    asset_id: UUID
    stream_key: str
    hls_manifest_url: str
    s3_prefix: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    violation_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class LiveViolationRead(BaseModel):
    id: UUID
    stream_id: UUID
    asset_id: UUID
    source_url: str
    platform: str
    confidence: float
    match_type: str
    severity: str
    watermark_payload: int | None
    segment_matched: str | None
    status: str
    detected_at: datetime
    dmca_triggered_at: datetime | None

    model_config = ConfigDict(from_attributes=True)


class LiveSegmentWatermarkRead(BaseModel):
    id: UUID
    stream_id: UUID
    segment_name: str
    payload: int
    s3_key: str
    watermarked_at: datetime

    model_config = ConfigDict(from_attributes=True)


class RegisterStreamRequest(BaseModel):
    asset_id: UUID
    stream_key: str = Field(..., min_length=3, max_length=64)
    hls_manifest_url: str
    s3_prefix: str


class SuspectUrlRequest(BaseModel):
    urls: list[str] = Field(..., min_length=1, max_length=20)


class WatermarkSegmentRequest(BaseModel):
    segment_name: str = Field(..., min_length=1, max_length=255)
    payload: int = Field(..., ge=0, le=0xFFFFFFFF)
