import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.asset import Asset


class LiveStream(Base):
    __tablename__ = "live_streams"
    __table_args__ = (
        Index("ix_live_streams_asset_id", "asset_id"),
        Index("ix_live_streams_status", "status"),
        Index("ix_live_streams_stream_key", "stream_key", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    stream_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    hls_manifest_url: Mapped[str] = mapped_column(Text, nullable=False)
    s3_prefix: Mapped[str] = mapped_column(String(1024), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="active", nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    asset: Mapped["Asset"] = relationship("Asset")
    watermarks: Mapped[list["LiveSegmentWatermark"]] = relationship(
        "LiveSegmentWatermark", back_populates="stream", cascade="all, delete-orphan"
    )
    violations: Mapped[list["LiveViolation"]] = relationship(
        "LiveViolation", back_populates="stream", cascade="all, delete-orphan"
    )


class LiveSegmentWatermark(Base):
    __tablename__ = "live_segment_watermarks"
    __table_args__ = (
        Index("ix_live_segment_watermarks_stream_id", "stream_id"),
        Index("ix_live_segment_watermarks_segment", "stream_id", "segment_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    stream_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("live_streams.id", ondelete="CASCADE"), nullable=False
    )
    segment_name: Mapped[str] = mapped_column(String(255), nullable=False)
    payload: Mapped[int] = mapped_column(Integer, nullable=False)
    viewer_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    watermarked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)

    stream: Mapped["LiveStream"] = relationship("LiveStream", back_populates="watermarks")


class LiveViolation(Base):
    __tablename__ = "live_violations"
    __table_args__ = (
        Index("ix_live_violations_stream_id", "stream_id"),
        Index("ix_live_violations_asset_id", "asset_id"),
        Index("ix_live_violations_status", "status"),
        Index("ix_live_violations_detected_at", "detected_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    stream_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("live_streams.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    match_type: Mapped[str] = mapped_column(String(16), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    watermark_payload: Mapped[int | None] = mapped_column(Integer, nullable=True)
    segment_matched: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="new", nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    dmca_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    stream: Mapped["LiveStream"] = relationship("LiveStream", back_populates="violations")
    asset: Mapped["Asset"] = relationship("Asset")
