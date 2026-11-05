"""initial schema: profiles, processed_events

Revision ID: 0001
Revises:
Create Date: 2026-11-05
"""
import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("role", sa.String(20), nullable=False, server_default="user"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_profiles_email", "profiles", ["email"])
    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("processed_events")
    op.drop_table("profiles")
