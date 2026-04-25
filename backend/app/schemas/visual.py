# app/schemas/visual.py
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Visual candidates
# ---------------------------------------------------------------------------

class DiscoverRequest(BaseModel):
    """Trigger a discovery scan for an asset.

    `query` seeds the search engine and acts as a filter for crawl results.
    Empty query means watchlist-only.
    """
    query: str | None = Field(default=None, max_length=255)
    max_candidates: int | None = Field(default=None, ge=1, le=200)


class DiscoverResponse(BaseModel):
    task_id: str
    status: str
    asset_id: UUID


class VisualCandidateRead(BaseModel):
    id: UUID
    asset_id: UUID
    source_url: str
    page_url: str | None
    platform: str
    thumbnail_url: str | None
    phash_distance: int | None
    clip_score: float | None
    visual_score: float
    discovered_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VisualCandidateList(BaseModel):
    asset_id: UUID
    total: int
    items: list[VisualCandidateRead]


# ---------------------------------------------------------------------------
# Watchlists
# ---------------------------------------------------------------------------

class WatchlistCreate(BaseModel):
    label: str = Field(min_length=1, max_length=255)
    root_url: str = Field(min_length=1, max_length=4096)
    platform: str | None = Field(default=None, max_length=32)
    enabled: bool = True


class WatchlistRead(BaseModel):
    id: UUID
    label: str
    root_url: str
    platform: str | None
    enabled: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class WatchlistList(BaseModel):
    total: int
    items: list[WatchlistRead]
    
class VisualFrameRead(BaseModel):
    id: UUID
    asset_id: UUID
    timestamp_ms: int
    phash: str
    has_clip_vector: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class VisualFrameList(BaseModel):
    asset_id: UUID
    total: int
    items: list[VisualFrameRead]