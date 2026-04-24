# app/schemas/alert.py
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AlertCreate(BaseModel):
    asset_id: UUID
    match_type: str = Field(min_length=1, max_length=32)
    confidence: float = Field(ge=0.0, le=1.0)
    infringing_url: str = Field(min_length=1, max_length=4096)
    platform: str | None = Field(default=None, max_length=32)


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

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
    assigned_to: str | None
    priority: str
    due_date: datetime | None
    created_at: datetime
    updated_at: datetime


class AlertStatusUpdate(BaseModel):
    status: str


class CaseUpdate(BaseModel):
    """All fields optional — PATCH semantics."""
    assigned_to: str | None = Field(default=None, max_length=128)
    priority: str | None = None
    due_date: datetime | None = None


class CommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4096)
    author: str = Field(min_length=1, max_length=128)


class CommentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    alert_id: UUID
    author: str
    body: str
    kind: str
    created_at: datetime


class DMCARequest(BaseModel):
    asset_owner: str
    contact_email: str
    asset_title: str | None = None
    infringing_url: str | None = None