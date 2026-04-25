"""add_visual_discovery

Revision ID: 20260425_visual_discovery
Revises: 20260424_evidence
Create Date: 2026-04-25
"""
from alembic import op
import sqlalchemy as sa


revision = "20260425_visual_discovery"
down_revision = "20260424_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "visual_asset_frames",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("timestamp_ms", sa.Integer(), nullable=False),
        sa.Column("frame_path", sa.String(length=1024), nullable=True),
        sa.Column("phash", sa.String(length=16), nullable=False),
        sa.Column("clip_vector", sa.LargeBinary(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_visual_asset_frames_asset_id", "visual_asset_frames", ["asset_id"])

    op.create_table(
        "visual_candidates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("page_url", sa.Text(), nullable=True),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("thumbnail_url", sa.Text(), nullable=True),
        sa.Column("phash_distance", sa.Integer(), nullable=True),
        sa.Column("clip_score", sa.Float(), nullable=True),
        sa.Column("visual_score", sa.Float(), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_visual_candidates_asset_id", "visual_candidates", ["asset_id"])

    op.create_table(
        "crawl_watchlists",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=False),
        sa.Column("root_url", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("crawl_watchlists")
    op.drop_index("ix_visual_candidates_asset_id", table_name="visual_candidates")
    op.drop_table("visual_candidates")
    op.drop_index("ix_visual_asset_frames_asset_id", table_name="visual_asset_frames")
    op.drop_table("visual_asset_frames")
