from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class FingerprintResult(BaseModel):
    asset_id: UUID
    frame_count: int = Field(ge=0)
    audio_window_count: int = Field(ge=0)
    duration_ms: int = Field(ge=0)


class FingerprintMatch(BaseModel):
    asset_id: UUID
    confidence: float = Field(ge=0.0, le=1.0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    match_type: Literal["frame", "audio", "fused"]

