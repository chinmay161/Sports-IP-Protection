"""add_evidence_packages

Revision ID: 20260424_evidence
Revises: 20260424_match_notes
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa


revision = "20260424_evidence"
down_revision = "20260424_match_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_packages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("match_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("manifest_s3_key", sa.String(length=1024), nullable=False),
        sa.Column("pdf_s3_key", sa.String(length=1024), nullable=False),
        sa.Column("package_hash", sa.String(length=64), nullable=False),
        sa.Column("thumbnail_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("match_id", name="uq_evidence_packages_match_id"),
    )


def downgrade() -> None:
    op.drop_table("evidence_packages")
