"""initial schema: bookings, outbox, processed_events

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
        "bookings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("user_email", sa.String(255), nullable=True),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("event_title", sa.String(200), nullable=False),
        sa.Column("event_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=False),
        sa.Column("category_name", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("cancel_reason", sa.String(200), nullable=True),
        sa.Column("payment_id", sa.Uuid(), nullable=True),
        sa.Column("idempotency_key", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_bookings_user_idempotency_key"),
    )
    op.create_index("ix_bookings_user_id", "bookings", ["user_id"])
    op.create_index("ix_bookings_event_id", "bookings", ["event_id"])
    op.create_index("ix_bookings_status", "bookings", ["status"])

    op.create_table(
        "outbox",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_outbox_published_at", "outbox", ["published_at"])

    op.create_table(
        "processed_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("processed_events")
    op.drop_table("outbox")
    op.drop_table("bookings")
