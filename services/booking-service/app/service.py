import contextlib
import logging
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from common.db import utcnow
from common.errors import ConflictError, NotFoundError
from common.outbox import add_outbox_event
from common.security import Principal

from .catalog_client import CatalogGateway
from .config import Settings
from .models import CANCELLED, CONFIRMED, PENDING_PAYMENT, Booking, OutboxEvent
from .schemas import BookingCreate

logger = logging.getLogger(__name__)


def booking_event(booking: Booking, **extra: object) -> dict:
    return {
        "booking_id": str(booking.id),
        "user_id": str(booking.user_id),
        "user_email": booking.user_email,
        "event_id": str(booking.event_id),
        "event_title": booking.event_title,
        "category_name": booking.category_name,
        "quantity": booking.quantity,
        "amount": f"{booking.total_amount:.2f}",
        "currency": booking.currency,
        "status": booking.status,
        **extra,
    }


class BookingService:
    def __init__(self, session: AsyncSession, catalog: CatalogGateway, settings: Settings) -> None:
        self.session = session
        self.catalog = catalog
        self.settings = settings

    async def _by_idempotency_key(self, user_id: uuid.UUID, key: str) -> Booking | None:
        return await self.session.scalar(select(Booking).where(Booking.user_id == user_id, Booking.idempotency_key == key))

    async def create(self, user: Principal, data: BookingCreate, idempotency_key: str | None) -> tuple[Booking, bool]:
        """Returns (booking, created). Step 1 of the saga: reserve tickets (gRPC) -> PENDING_PAYMENT + booking.created."""
        if idempotency_key:
            existing = await self._by_idempotency_key(user.user_id, idempotency_key)
            if existing is not None:
                logger.info("Idempotent replay", extra={"booking_id": str(existing.id)})
                return existing, False

        booking_id = uuid.uuid4()
        reservation = await self.catalog.reserve(booking_id, data.category_id, data.quantity)

        booking = Booking(
            id=booking_id,
            user_id=user.user_id,
            user_email=user.email,
            event_id=reservation.event_id,
            event_title=reservation.event_title,
            event_starts_at=reservation.starts_at,
            category_id=reservation.category_id,
            category_name=reservation.category_name,
            quantity=reservation.quantity,
            unit_price=reservation.unit_price,
            total_amount=reservation.total_price,
            currency=self.settings.currency,
            status=PENDING_PAYMENT,
            idempotency_key=idempotency_key,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        self.session.add(booking)
        add_outbox_event(self.session, OutboxEvent, "booking.created", booking_event(booking))
        try:
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            # Compensation: do not leave tickets reserved for a booking that was never stored.
            with contextlib.suppress(Exception):
                await self.catalog.release(booking_id)
            if isinstance(exc, IntegrityError) and idempotency_key:
                existing = await self._by_idempotency_key(user.user_id, idempotency_key)
                if existing is not None:
                    return existing, False
            raise
        logger.info("Booking created", extra={"booking_id": str(booking.id), "amount": str(booking.total_amount)})
        return booking, True

    async def get_for_user(self, booking_id: uuid.UUID, user: Principal) -> Booking:
        booking = await self.session.get(Booking, booking_id)
        if booking is None or (booking.user_id != user.user_id and not user.is_admin):
            raise NotFoundError("Booking not found")  # 404 (not 403) to avoid leaking other users' ids
        return booking

    async def list(
        self, user: Principal, *, status: str | None, user_id: uuid.UUID | None, limit: int, offset: int
    ) -> tuple[list[Booking], int]:
        query = select(Booking)
        if not user.is_admin:
            query = query.where(Booking.user_id == user.user_id)
        elif user_id:
            query = query.where(Booking.user_id == user_id)
        if status:
            query = query.where(Booking.status == status)
        total = await self.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = await self.session.scalars(query.order_by(Booking.created_at.desc()).limit(limit).offset(offset))
        return list(rows.all()), total

    async def cancel(self, booking_id: uuid.UUID, user: Principal) -> Booking:
        booking = await self.get_for_user(booking_id, user)
        if booking.status == CANCELLED:
            raise ConflictError("Booking is already cancelled", code="already_cancelled")
        await self.catalog.release(booking.id)
        booking.status = CANCELLED
        booking.cancel_reason = "cancelled_by_user"
        booking.updated_at = utcnow()
        add_outbox_event(self.session, OutboxEvent, "booking.cancelled", booking_event(booking, reason="cancelled_by_user"))
        await self.session.commit()
        logger.info("Booking cancelled by user", extra={"booking_id": str(booking.id)})
        return booking


class SagaHandlers:
    """Reactions to payment events (choreography saga)."""

    def __init__(self, session: AsyncSession, catalog: CatalogGateway) -> None:
        self.session = session
        self.catalog = catalog

    async def payment_succeeded(self, payload: dict) -> None:
        booking = await self.session.get(Booking, uuid.UUID(payload["booking_id"]))
        if booking is None:
            logger.error("Payment for unknown booking", extra={"booking_id": payload["booking_id"]})
            return
        if booking.status != PENDING_PAYMENT:
            # e.g. user cancelled before the payment arrived: payment-service refunds on booking.cancelled
            logger.info("Payment ignored, booking not pending", extra={"booking_id": str(booking.id), "status": booking.status})
            return
        await self.catalog.confirm(booking.id)
        booking.status = CONFIRMED
        booking.payment_id = uuid.UUID(payload["payment_id"])
        booking.updated_at = utcnow()
        add_outbox_event(self.session, OutboxEvent, "booking.confirmed", booking_event(booking, payment_id=payload["payment_id"]))
        logger.info("Booking confirmed", extra={"booking_id": str(booking.id)})

    async def payment_failed(self, payload: dict) -> None:
        booking = await self.session.get(Booking, uuid.UUID(payload["booking_id"]))
        if booking is None or booking.status != PENDING_PAYMENT:
            return
        await self.catalog.release(booking.id)  # compensation: return tickets to the pool
        reason = f"payment_failed: {payload.get('reason', 'unknown')}"
        booking.status = CANCELLED
        booking.cancel_reason = reason[:200]
        booking.updated_at = utcnow()
        add_outbox_event(self.session, OutboxEvent, "booking.cancelled", booking_event(booking, reason=reason))
        logger.info("Booking cancelled after failed payment", extra={"booking_id": str(booking.id)})
