import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class WatermarkRegistry(Base):
    __tablename__ = "watermark_registry"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    payload: Mapped[int] = mapped_column(Integer, nullable=False)
    alpha: Mapped[int] = mapped_column(Integer, default=8, nullable=False)
    keyframe_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    psnr_mean: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    asset: Mapped["Asset"] = relationship("Asset", back_populates="watermark_registry")  # noqa: F821
