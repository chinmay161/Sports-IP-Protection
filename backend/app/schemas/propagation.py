from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class GraphNode(BaseModel):
    id: str
    type: str
    platform: str
    channel: str | None
    url: str
    view_count: int | None
    confidence: float
    severity: str
    geo_country: str | None
    detected_at: datetime
    status: str


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relation: str
    delta_ms: int


class GraphMeta(BaseModel):
    node_count: int
    edge_count: int
    platform_spread: dict[str, int]
    first_detected_at: datetime
    spread_duration_ms: int
    origin_country: str | None


class PropagationGraph(BaseModel):
    match_id: UUID
    generated_at: datetime
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    meta: GraphMeta


class TimelineBucket(BaseModel):
    bucket_start: datetime
    new_nodes: int
    cumulative_nodes: int
    cumulative_views: int


class PropagationTimeline(BaseModel):
    match_id: UUID
    bucket_size_ms: int
    buckets: list[TimelineBucket]
    peak_bucket: datetime
    velocity_index: float


class PropagationSummary(BaseModel):
    asset_id: UUID
    total_infringing_copies: int
    total_estimated_views: int
    platforms_reached: list[str]
    countries_reached: int
    fastest_repost_ms: int | None
    origin_platform: str | None
    peak_velocity_index: float
