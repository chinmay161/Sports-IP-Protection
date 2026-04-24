import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.match import Match


class EvidencePackage(Base):
    __tablename__ = "evidence_packages"
    __table_args__ = (UniqueConstraint("match_id", name="uq_evidence_packages_match_id"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    match_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("matches.id", ondelete="CASCADE"), nullable=False
    )
    asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assets.id", ondelete="CASCADE"), nullable=False
    )
    manifest_s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    pdf_s3_key: Mapped[str] = mapped_column(String(1024), nullable=False)
    package_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    thumbnail_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    match: Mapped["Match"] = relationship("Match")
    asset: Mapped["Asset"] = relationship("Asset")
