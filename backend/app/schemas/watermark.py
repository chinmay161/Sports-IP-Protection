from uuid import UUID

from pydantic import BaseModel, Field


class WatermarkRequest(BaseModel):
    payload: int = Field(ge=0, le=0xFFFFFFFF)
    alpha: int = Field(default=8, ge=1)


class WatermarkScanRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)


class WatermarkResult(BaseModel):
    asset_id: UUID
    payload: int
    keyframe_count: int
    s3_key: str
    psnr_mean: float


class WatermarkDetection(BaseModel):
    payload: int
    asset_id: UUID | None
    confidence: float
    frames_agreed: int
