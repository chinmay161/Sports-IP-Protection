# app/schemas/alert.py
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AlertCreate(BaseModel):
    asset_id: UUID
    match_type: str
    confidence: float = Field(ge=0.0, le=1.0)
    infringing_url: str
    platform: str | None = None


class AlertResponse(BaseModel):
    id: UUID
    asset_id: UUID
    status: str
    severity_score: float
    severity_label: str
    match_type: str
    confidence: float
    infringing_url: str
    platform: str | None
    ai_reasoning: str | None
    dmca_notice: str | None
    notified_email: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AlertStatusUpdate(BaseModel):
    status: str


class DMCARequest(BaseModel):
    asset_title: str
    asset_owner: str
    infringing_url: str
    contact_email: str