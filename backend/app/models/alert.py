# app/models/alert.py
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.comment import CaseComment


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    asset_id: Mapped[str] = mapped_column(String(36), ForeignKey("assets.id"), nullable=False)

    # Core alert fields
    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False)
    severity_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    severity_label: Mapped[str] = mapped_column(String(16), default="low", nullable=False)
    match_type: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    infringing_url: Mapped[str] = mapped_column(Text, nullable=False)
    platform: Mapped[str | None] = mapped_column(String(32), nullable=True)
    ai_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    dmca_notice: Mapped[str | None] = mapped_column(Text, nullable=True)
    notified_email: Mapped[bool] = mapped_column(default=False, nullable=False)

    # Case management fields
    assigned_to: Mapped[str | None] = mapped_column(String(128), nullable=True)
    priority: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)
    due_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    asset: Mapped["Asset"] = relationship("Asset", back_populates="alerts")
    comments: Mapped[list["CaseComment"]] = relationship(
        "CaseComment",
        back_populates="alert",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="CaseComment.created_at.desc()",
    )