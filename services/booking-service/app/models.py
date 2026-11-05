import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from common.db import utcnow
from common.outbox import OutboxMixin, ProcessedEventMixin

PENDING_PAYMENT = "PENDING_PAYMENT"
CONFIRMED = "CONFIRMED"
CANCELLED = "CANCELLED"


class Base(DeclarativeBase):
    pass


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key", name="uq_bookings_user_idempotency_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    user_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    event_title: Mapped[str] = mapped_column(String(200))
    event_starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    category_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    category_name: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default=PENDING_PAYMENT, index=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OutboxEvent(OutboxMixin, Base):
    pass


class ProcessedEvent(ProcessedEventMixin, Base):
    pass
