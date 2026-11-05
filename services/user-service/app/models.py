import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from common.db import utcnow
from common.outbox import ProcessedEventMixin


class Base(DeclarativeBase):
    pass


class Profile(Base):
    """User profile. The id is the same as in auth-service; the profile is created
    asynchronously from the `user.registered` event (no synchronous coupling to auth)."""

    __tablename__ = "profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(String(20), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ProcessedEvent(ProcessedEventMixin, Base):
    pass
