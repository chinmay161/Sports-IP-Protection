# app/models/alert.py
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(32), default="open", nullable=False
    )  # open | acknowledged | dmca_initiated | resolved
    severity_score: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )  # 0.0 - 1.0
    severity_label: Mapped[str] = mapped_column(
        String(16), nullable=False, default="low"
    )  # low | medium | high | critical
    match_type: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    infringing_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    platform: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ai_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    dmca_notice: Mapped[str | None] = mapped_column(Text, nullable=True)
    notified_email: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    asset: Mapped["Asset"] = relationship("Asset", back_populates="alerts")  # noqa: F821