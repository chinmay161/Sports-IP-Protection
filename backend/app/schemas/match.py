from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MatchSegmentRead(BaseModel):
    id: UUID
    match_id: UUID
    asset_start_ms: int
    asset_end_ms: int
    source_start_ms: int
    source_end_ms: int
    frame_run_length: int
    audio_confidence: float | None
    thumbnail_s3_key: str | None
    model_config = ConfigDict(from_attributes=True)


class MatchRead(BaseModel):
    id: UUID
    asset_id: UUID
    source_url: str
    platform: str
    confidence: float
    match_type: str
    severity: str
    watermark_payload: int | None
    source_channel: str | None
    view_count: int | None
    duration_matched_ms: int
    status: str
    geo_country: str | None
    detected_at: datetime
    alerted_at: datetime | None
    resolved_at: datetime | None
    segments: list[MatchSegmentRead] = []
    model_config = ConfigDict(from_attributes=True)


class AcknowledgeRequest(BaseModel):
    note: str | None = None


class ScanRequest(BaseModel):
    asset_id: UUID
    max_per_platform: int = Field(default=10, ge=1, le=50)


class ScanResponse(BaseModel):
    task_id: str
    status: str


class DmcaResponse(BaseModel):
    match_id: UUID
    status: str
    task_id: str


class EvidenceResponse(BaseModel):
    download_url: str
    expires_in: int


class StatsResponse(BaseModel):
    total_matches: int
    by_severity: dict[str, int]
    by_platform: dict[str, int]
    by_status: dict[str, int]
    top_infringing_countries: list[dict[str, Any]]
