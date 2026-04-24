"""add_match_notes

Revision ID: 20260424_match_notes
Revises: 20260424_matches
Create Date: 2026-04-24
"""
from alembic import op
import sqlalchemy as sa


revision = "20260424_match_notes"
down_revision = "20260424_matches"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "match_notes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("match_id", sa.String(length=36), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["match_id"], ["matches.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("match_notes")
