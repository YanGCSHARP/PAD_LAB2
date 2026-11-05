import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from common.db import utcnow


class Base(DeclarativeBase):
    pass


class Venue(Base):
    __tablename__ = "venues"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100), index=True)
    address: Mapped[str] = mapped_column(String(300))
    capacity: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Event(Base):
    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    venue_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("venues.id", ondelete="RESTRICT"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(50), default="concert")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(20), default="on_sale")  # on_sale | draft | cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    venue: Mapped[Venue] = relationship(lazy="selectin")
    ticket_categories: Mapped[list["TicketCategory"]] = relationship(
        back_populates="event", lazy="selectin", cascade="all, delete-orphan", order_by="TicketCategory.price"
    )


class TicketCategory(Base):
    __tablename__ = "ticket_categories"
    __table_args__ = (
        CheckConstraint("available >= 0", name="ck_available_non_negative"),
        CheckConstraint("available <= total", name="ck_available_le_total"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("events.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    total: Mapped[int] = mapped_column(Integer)
    available: Mapped[int] = mapped_column(Integer)

    event: Mapped[Event] = relationship(back_populates="ticket_categories", lazy="selectin")


class Reservation(Base):
    """Tickets held for a booking. Primary key = booking_id makes every gRPC call idempotent."""

    __tablename__ = "reservations"

    booking_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    category_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ticket_categories.id"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="reserved")  # reserved | confirmed | released
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
