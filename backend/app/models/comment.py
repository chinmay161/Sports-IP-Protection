# app/models/comment.py
from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CaseComment(Base):
    """A comment or system event on an alert/case.

    `kind` distinguishes user comments from auto-generated system events
    (status changes, assignments). The UI renders them differently but they
    share one ordered timeline so the activity log reads naturally.
    """
    __tablename__ = "case_comments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    alert_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("alerts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    author: Mapped[str] = mapped_column(String(128), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="user", nullable=False)  # user | system

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    alert: Mapped["Alert"] = relationship("Alert", back_populates="comments")