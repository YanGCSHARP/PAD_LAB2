import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class BookingCreate(BaseModel):
    category_id: uuid.UUID = Field(description="Ticket category id from GET /api/events/{id}")
    quantity: int = Field(ge=1, le=10, examples=[2])


class BookingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    event_id: uuid.UUID
    event_title: str
    event_starts_at: datetime
    category_id: uuid.UUID
    category_name: str
    quantity: int
    unit_price: Decimal
    total_amount: Decimal
    currency: str
    status: str = Field(description="PENDING_PAYMENT -> CONFIRMED | CANCELLED")
    cancel_reason: str | None
    payment_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
