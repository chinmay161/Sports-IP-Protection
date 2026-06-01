"""initial_core_tables

Revision ID: 20260420_initial_core
Revises:
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa


revision = "20260420_initial_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("download_status", sa.String(length=32), nullable=False, server_default="n/a"),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("video_path", sa.String(length=1024), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("severity_score", sa.Float(), nullable=False),
        sa.Column("severity_label", sa.String(length=16), nullable=False),
        sa.Column("match_type", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("infringing_url", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(length=32), nullable=True),
        sa.Column("ai_reasoning", sa.Text(), nullable=True),
        sa.Column("dmca_notice", sa.Text(), nullable=True),
        sa.Column("notified_email", sa.Boolean(), nullable=False),
        sa.Column("assigned_to", sa.String(length=128), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("due_date", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "case_comments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("alert_id", sa.String(length=36), nullable=False),
        sa.Column("author", sa.String(length=128), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["alert_id"], ["alerts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_case_comments_alert_id", "case_comments", ["alert_id"])


def downgrade() -> None:
    op.drop_index("ix_case_comments_alert_id", table_name="case_comments")
    op.drop_table("case_comments")
    op.drop_table("alerts")
    op.drop_table("assets")
