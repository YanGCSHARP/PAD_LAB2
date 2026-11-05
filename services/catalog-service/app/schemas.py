import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EventStatus = Literal["on_sale", "draft", "cancelled"]
EventCategory = Literal["concert", "theatre", "sport", "festival", "conference", "other"]


class VenueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200, examples=["Palatul Republicii"])
    city: str = Field(min_length=1, max_length=100, examples=["Chisinau"])
    address: str = Field(min_length=1, max_length=300, examples=["str. Maria Cibotari 16"])
    capacity: int = Field(gt=0, le=200_000)


class VenueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    city: str
    address: str
    capacity: int


class TicketCategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["Standard"])
    price: Decimal = Field(gt=0, max_digits=10, decimal_places=2, examples=["450.00"])
    total: int = Field(gt=0, le=200_000)


class TicketCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    price: Decimal
    total: int
    available: int


class EventCreate(BaseModel):
    venue_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    description: str = Field("", max_length=5000)
    category: EventCategory = "concert"
    starts_at: datetime
    status: EventStatus = "on_sale"
    ticket_categories: list[TicketCategoryIn] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique_category_names(self) -> "EventCreate":
        names = [c.name.lower() for c in self.ticket_categories]
        if len(names) != len(set(names)):
            raise ValueError("ticket category names must be unique")
        if self.starts_at.tzinfo is None:
            raise ValueError("starts_at must include a timezone")
        return self


class EventUpdate(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=5000)
    starts_at: datetime | None = None
    status: EventStatus | None = None


class EventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    description: str
    category: str
    starts_at: datetime
    status: str
    venue: VenueOut
    ticket_categories: list[TicketCategoryOut]
