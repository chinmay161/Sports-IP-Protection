"""add_incident_summary

Revision ID: 20260426_incident_summary
Revises: 20260426_gemini_verification
Create Date: 2026-04-26
"""
from alembic import op
import sqlalchemy as sa


revision = "20260426_incident_summary"
down_revision = "20260426_gemini_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("evidence_packages", sa.Column("incident_summary", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("evidence_packages", "incident_summary")
