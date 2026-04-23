"""add_watermark_registry

Revision ID: 20260423_watermark
Revises:
Create Date: 2026-04-23
"""
from alembic import op
import sqlalchemy as sa


revision = "20260423_watermark"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("fingerprint_status", sa.String(length=32), nullable=False, server_default="pending"))
    op.add_column("assets", sa.Column("watermark_status", sa.String(length=32), nullable=False, server_default="pending"))
    op.create_table(
        "watermark_registry",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("payload", sa.Integer(), nullable=False),
        sa.Column("alpha", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("keyframe_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("psnr_mean", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("asset_id"),
    )


def downgrade() -> None:
    op.drop_table("watermark_registry")
    op.drop_column("assets", "watermark_status")
    op.drop_column("assets", "fingerprint_status")
