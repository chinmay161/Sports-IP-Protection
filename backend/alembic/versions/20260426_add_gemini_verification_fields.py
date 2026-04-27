"""add_gemini_verification_fields

Revision ID: 20260426_gemini_verification
Revises: 20260425_visual_discovery
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa


revision = "20260426_gemini_verification"
down_revision = "20260425_visual_discovery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("matches", sa.Column("gemini_verification_reason", sa.Text(), nullable=True))
    op.add_column("matches", sa.Column("gemini_is_sports_content", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("matches", "gemini_is_sports_content")
    op.drop_column("matches", "gemini_verification_reason")
