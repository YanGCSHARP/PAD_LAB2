import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from common.db import utcnow
from common.outbox import OutboxMixin, ProcessedEventMixin

PENDING = "PENDING"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
REFUNDED = "REFUNDED"
CANCELLED = "CANCELLED"  # booking was cancelled before it was charged


class Base(DeclarativeBase):
    pass


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(Uuid, unique=True)  # one payment per booking -> idempotent
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(20), default=PENDING)
    failure_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OutboxEvent(OutboxMixin, Base):
    pass


class ProcessedEvent(ProcessedEventMixin, Base):
    pass
