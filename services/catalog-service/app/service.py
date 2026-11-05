import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from common.db import ensure_aware, utcnow
from common.errors import BadRequestError, ConflictError, NotFoundError

from .models import Event, Reservation, TicketCategory, Venue
from .schemas import EventCreate, EventUpdate, VenueCreate

logger = logging.getLogger(__name__)


class CatalogService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---- venues -------------------------------------------------------------------------
    async def create_venue(self, data: VenueCreate) -> Venue:
        venue = Venue(id=uuid.uuid4(), created_at=utcnow(), **data.model_dump())
        self.session.add(venue)
        await self.session.commit()
        logger.info("Venue created", extra={"venue_id": str(venue.id)})
        return venue

    async def list_venues(self, city: str | None) -> list[Venue]:
        query = select(Venue).order_by(Venue.name)
        if city:
            query = query.where(func.lower(Venue.city) == city.lower())
        return list((await self.session.scalars(query)).all())

    async def get_venue(self, venue_id: uuid.UUID) -> Venue:
        venue = await self.session.get(Venue, venue_id)
        if venue is None:
            raise NotFoundError("Venue not found")
        return venue

    # ---- events -------------------------------------------------------------------------
    async def list_events(
        self, *, q: str | None, city: str | None, category: str | None, date_from: datetime | None,
        date_to: datetime | None, include_past: bool, limit: int, offset: int,
    ) -> tuple[list[Event], int]:
        query = select(Event).join(Venue).where(Event.status != "draft")
        if not include_past:
            query = query.where(Event.starts_at >= utcnow())
        if q:
            pattern = f"%{q.lower()}%"
            query = query.where(or_(func.lower(Event.title).like(pattern), func.lower(Event.description).like(pattern)))
        if city:
            query = query.where(func.lower(Venue.city) == city.lower())
        if category:
            query = query.where(Event.category == category)
        if date_from:
            query = query.where(Event.starts_at >= date_from)
        if date_to:
            query = query.where(Event.starts_at <= date_to)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = await self.session.scalars(query.order_by(Event.starts_at).limit(limit).offset(offset))
        return list(rows.all()), total

    async def get_event(self, event_id: uuid.UUID) -> Event:
        event = await self.session.scalar(
            select(Event)
            .where(Event.id == event_id)
            .options(selectinload(Event.venue), selectinload(Event.ticket_categories))
            .execution_options(populate_existing=True)
        )
        if event is None:
            raise NotFoundError("Event not found")
        return event

    async def create_event(self, data: EventCreate) -> Event:
        venue = await self.get_venue(data.venue_id)
        if data.starts_at <= utcnow():
            raise BadRequestError("Event must start in the future", code="invalid_date")
        seats = sum(c.total for c in data.ticket_categories)
        if seats > venue.capacity:
            raise BadRequestError(
                f"Total tickets ({seats}) exceed venue capacity ({venue.capacity})", code="capacity_exceeded"
            )
        event = Event(
            id=uuid.uuid4(),
            venue_id=venue.id,
            title=data.title,
            description=data.description,
            category=data.category,
            starts_at=data.starts_at.astimezone(UTC),
            status=data.status,
            created_at=utcnow(),
            ticket_categories=[
                TicketCategory(id=uuid.uuid4(), name=c.name, price=c.price, total=c.total, available=c.total)
                for c in data.ticket_categories
            ],
        )
        self.session.add(event)
        await self.session.commit()
        logger.info("Event created", extra={"event_id": str(event.id)})
        return await self.get_event(event.id)

    async def update_event(self, event_id: uuid.UUID, data: EventUpdate) -> Event:
        event = await self.get_event(event_id)
        changes = data.model_dump(exclude_unset=True, exclude_none=True)
        if "starts_at" in changes and changes["starts_at"] <= utcnow():
            raise BadRequestError("Event must start in the future", code="invalid_date")
        if "starts_at" in changes:
            changes["starts_at"] = changes["starts_at"].astimezone(UTC)
        for field, value in changes.items():
            setattr(event, field, value)
        await self.session.commit()
        logger.info("Event updated", extra={"event_id": str(event_id), "fields": list(changes)})
        return await self.get_event(event_id)

    async def delete_event(self, event_id: uuid.UUID) -> None:
        event = await self.get_event(event_id)
        category_ids = [c.id for c in event.ticket_categories]
        has_reservations = await self.session.scalar(
            select(func.count()).select_from(Reservation).where(Reservation.category_id.in_(category_ids))
        )
        if has_reservations:
            raise ConflictError("Event has bookings; set status=cancelled instead", code="event_has_bookings")
        await self.session.delete(event)
        await self.session.commit()
        logger.info("Event deleted", extra={"event_id": str(event_id)})


@dataclass
class ReservationInfo:
    booking_id: uuid.UUID
    event_id: uuid.UUID
    event_title: str
    category_id: uuid.UUID
    category_name: str
    quantity: int
    unit_price: Decimal
    status: str
    starts_at: datetime

    @property
    def total_price(self) -> Decimal:
        return self.unit_price * self.quantity


class ReservationService:
    """Ticket inventory operations used by booking-service over gRPC. All operations are idempotent."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _info(self, reservation: Reservation) -> ReservationInfo:
        category = await self.session.get(TicketCategory, reservation.category_id)
        assert category is not None
        event = category.event
        return ReservationInfo(
            booking_id=reservation.booking_id,
            event_id=event.id,
            event_title=event.title,
            category_id=category.id,
            category_name=category.name,
            quantity=reservation.quantity,
            unit_price=Decimal(category.price),
            status=reservation.status,
            starts_at=ensure_aware(event.starts_at),
        )

    async def reserve(self, booking_id: uuid.UUID, category_id: uuid.UUID, quantity: int) -> ReservationInfo:
        if quantity < 1 or quantity > 10:
            raise BadRequestError("Quantity must be between 1 and 10", code="invalid_quantity")
        existing = await self.session.get(Reservation, booking_id)
        if existing is not None:
            return await self._info(existing)

        category = await self.session.get(TicketCategory, category_id)
        if category is None:
            raise NotFoundError("Ticket category not found", code="category_not_found")
        event = category.event
        if event.status != "on_sale" or ensure_aware(event.starts_at) <= utcnow():
            raise ConflictError("Event is not on sale", code="not_on_sale")

        # Atomic conditional decrement: no overselling even under concurrent requests.
        result = await self.session.execute(
            update(TicketCategory)
            .where(TicketCategory.id == category_id, TicketCategory.available >= quantity)
            .values(available=TicketCategory.available - quantity)
        )
        if result.rowcount == 0:
            await self.session.rollback()
            raise ConflictError("Not enough tickets available", code="sold_out")

        reservation = Reservation(booking_id=booking_id, category_id=category_id, quantity=quantity,
                                  status="reserved", created_at=utcnow(), updated_at=utcnow())
        self.session.add(reservation)
        await self.session.commit()
        await self.session.refresh(category)
        logger.info("Tickets reserved", extra={"booking_id": str(booking_id), "quantity": quantity, "left": category.available})
        return await self._info(reservation)

    async def confirm(self, booking_id: uuid.UUID) -> ReservationInfo:
        reservation = await self.session.get(Reservation, booking_id)
        if reservation is None:
            raise NotFoundError("Reservation not found", code="reservation_not_found")
        if reservation.status == "released":
            raise ConflictError("Reservation was already released", code="reservation_released")
        if reservation.status != "confirmed":
            reservation.status = "confirmed"
            reservation.updated_at = utcnow()
            await self.session.commit()
            logger.info("Reservation confirmed", extra={"booking_id": str(booking_id)})
        return await self._info(reservation)

    async def release(self, booking_id: uuid.UUID) -> ReservationInfo | None:
        reservation = await self.session.get(Reservation, booking_id)
        if reservation is None:
            return None
        if reservation.status != "released":
            await self.session.execute(
                update(TicketCategory)
                .where(TicketCategory.id == reservation.category_id)
                .values(available=TicketCategory.available + reservation.quantity)
            )
            reservation.status = "released"
            reservation.updated_at = utcnow()
            await self.session.commit()
            logger.info("Tickets released", extra={"booking_id": str(booking_id), "quantity": reservation.quantity})
        return await self._info(reservation)
