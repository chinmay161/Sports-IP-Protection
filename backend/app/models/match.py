import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.asset import Asset


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (
        Index("ix_matches_asset_id", "asset_id"),
        Index("ix_matches_status", "status"),
        Index("ix_matches_severity", "severity"),
        Index("ix_matches_detected_at_desc", "detected_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
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
    source_channel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    view_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_matched_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="new", nullable=False)
    geo_country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    asset: Mapped["Asset"] = relationship("Asset")  # noqa: F821
    segments: Mapped[list["MatchSegment"]] = relationship(
        "MatchSegment", back_populates="match", cascade="all, delete-orphan"
    )
    notes: Mapped[list["MatchNote"]] = relationship(
        "MatchNote", back_populates="match", cascade="all, delete-orphan"
    )


class MatchSegment(Base):
    __tablename__ = "match_segments"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    match_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    asset_start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    asset_end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    source_start_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    source_end_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    frame_run_length: Mapped[int] = mapped_column(Integer, nullable=False)
    audio_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    thumbnail_s3_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    match: Mapped["Match"] = relationship("Match", back_populates="segments")


class MatchNote(Base):
    __tablename__ = "match_notes"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    match_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    note: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    match: Mapped["Match"] = relationship("Match", back_populates="notes")
