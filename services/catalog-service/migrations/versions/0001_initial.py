"""initial schema: venues, events, ticket_categories, reservations

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
        "venues",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("address", sa.String(300), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_venues_city", "venues", ["city"])

    op.create_table(
        "events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("venue_id", sa.Uuid(), sa.ForeignKey("venues.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(50), nullable=False, server_default="concert"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="on_sale"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_events_venue_id", "events", ["venue_id"])
    op.create_index("ix_events_starts_at", "events", ["starts_at"])

    op.create_table(
        "ticket_categories",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_id", sa.Uuid(), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("available", sa.Integer(), nullable=False),
        sa.CheckConstraint("available >= 0", name="ck_available_non_negative"),
        sa.CheckConstraint("available <= total", name="ck_available_le_total"),
    )
    op.create_index("ix_ticket_categories_event_id", "ticket_categories", ["event_id"])

    op.create_table(
        "reservations",
        sa.Column("booking_id", sa.Uuid(), primary_key=True),
        sa.Column("category_id", sa.Uuid(), sa.ForeignKey("ticket_categories.id"), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="reserved"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_reservations_category_id", "reservations", ["category_id"])


def downgrade() -> None:
    op.drop_table("reservations")
    op.drop_table("ticket_categories")
    op.drop_table("events")
    op.drop_table("venues")
