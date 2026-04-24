"""add_matches_and_match_segments

Revision ID: 20260424_matches
Revises: 20260423_watermark
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa


revision = "20260424_matches"
down_revision = "20260423_watermark"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "matches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("match_type", sa.String(length=16), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("watermark_payload", sa.Integer(), nullable=True),
        sa.Column("source_channel", sa.String(length=255), nullable=True),
        sa.Column("view_count", sa.Integer(), nullable=True),
        sa.Column("duration_matched_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="new"),
        sa.Column("geo_country", sa.String(length=2), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("alerted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_matches_asset_id", "matches", ["asset_id"])
    op.create_index("ix_matches_status", "matches", ["status"])
    op.create_index("ix_matches_severity", "matches", ["severity"])
    op.create_index("ix_matches_detected_at_desc", "matches", [sa.text("detected_at DESC")])

    op.create_table(
        "match_segments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("match_id", sa.String(length=36), nullable=False),
        sa.Column("asset_start_ms", sa.Integer(), nullable=False),
        sa.Column("asset_end_ms", sa.Integer(), nullable=False),
        sa.Column("source_start_ms", sa.Integer(), nullable=False),
        sa.Column("source_end_ms", sa.Integer(), nullable=False),
        sa.Column("frame_run_length", sa.Integer(), nullable=False),
        sa.Column("audio_confidence", sa.Float(), nullable=True),
        sa.Column("thumbnail_s3_key", sa.String(length=1024), nullable=True),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("match_segments")
    op.drop_index("ix_matches_detected_at_desc", table_name="matches")
    op.drop_index("ix_matches_severity", table_name="matches")
    op.drop_index("ix_matches_status", table_name="matches")
    op.drop_index("ix_matches_asset_id", table_name="matches")
    op.drop_table("matches")
