"""add_live_stream_tables

Revision ID: 20260427_live_stream_tables
Revises: 20260426_incident_summary
Create Date: 2026-04-27
"""
from alembic import op
import sqlalchemy as sa


revision = "20260427_live_stream_tables"
down_revision = "20260426_incident_summary"
branch_labels = None
depends_on = None


def _existing_tables() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def _existing_indexes(table_name: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _create_index_if_missing(name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    if name not in _existing_indexes(table_name):
        op.create_index(name, table_name, columns, unique=unique)


def upgrade() -> None:
    tables = _existing_tables()
    if "live_streams" not in tables:
        op.create_table(
            "live_streams",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("asset_id", sa.String(length=36), nullable=False),
            sa.Column("stream_key", sa.String(length=64), nullable=False),
            sa.Column("hls_manifest_url", sa.Text(), nullable=False),
            sa.Column("s3_prefix", sa.String(length=1024), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("stream_key"),
        )
    _create_index_if_missing("ix_live_streams_asset_id", "live_streams", ["asset_id"])
    _create_index_if_missing("ix_live_streams_status", "live_streams", ["status"])
    _create_index_if_missing("ix_live_streams_stream_key", "live_streams", ["stream_key"], unique=True)

    tables = _existing_tables()
    if "live_segment_watermarks" not in tables:
        op.create_table(
            "live_segment_watermarks",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("stream_id", sa.String(length=36), nullable=False),
            sa.Column("segment_name", sa.String(length=255), nullable=False),
            sa.Column("payload", sa.Integer(), nullable=False),
            sa.Column("viewer_token", sa.String(length=255), nullable=True),
            sa.Column("watermarked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("s3_key", sa.String(length=1024), nullable=False),
            sa.ForeignKeyConstraint(["stream_id"], ["live_streams.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_live_segment_watermarks_stream_id", "live_segment_watermarks", ["stream_id"])
    _create_index_if_missing(
        "ix_live_segment_watermarks_segment",
        "live_segment_watermarks",
        ["stream_id", "segment_name"],
    )

    tables = _existing_tables()
    if "live_violations" not in tables:
        op.create_table(
            "live_violations",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("stream_id", sa.String(length=36), nullable=False),
            sa.Column("asset_id", sa.String(length=36), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=False),
            sa.Column("platform", sa.String(length=32), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False),
            sa.Column("match_type", sa.String(length=16), nullable=False),
            sa.Column("severity", sa.String(length=8), nullable=False),
            sa.Column("watermark_payload", sa.Integer(), nullable=True),
            sa.Column("segment_matched", sa.String(length=1024), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("dmca_triggered_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["stream_id"], ["live_streams.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
    _create_index_if_missing("ix_live_violations_stream_id", "live_violations", ["stream_id"])
    _create_index_if_missing("ix_live_violations_asset_id", "live_violations", ["asset_id"])
    _create_index_if_missing("ix_live_violations_status", "live_violations", ["status"])
    _create_index_if_missing("ix_live_violations_detected_at", "live_violations", ["detected_at"])


def downgrade() -> None:
    op.drop_index("ix_live_violations_detected_at", table_name="live_violations")
    op.drop_index("ix_live_violations_status", table_name="live_violations")
    op.drop_index("ix_live_violations_asset_id", table_name="live_violations")
    op.drop_index("ix_live_violations_stream_id", table_name="live_violations")
    op.drop_table("live_violations")

    op.drop_index("ix_live_segment_watermarks_segment", table_name="live_segment_watermarks")
    op.drop_index("ix_live_segment_watermarks_stream_id", table_name="live_segment_watermarks")
    op.drop_table("live_segment_watermarks")

    op.drop_index("ix_live_streams_stream_key", table_name="live_streams")
    op.drop_index("ix_live_streams_status", table_name="live_streams")
    op.drop_index("ix_live_streams_asset_id", table_name="live_streams")
    op.drop_table("live_streams")
