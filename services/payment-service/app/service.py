import logging
import uuid
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db import utcnow
from common.outbox import add_outbox_event

from .models import CANCELLED, FAILED, PENDING, REFUNDED, SUCCEEDED, OutboxEvent, Payment
from .provider import FakePaymentProvider

logger = logging.getLogger(__name__)


def payment_event(payment: Payment, **extra: object) -> dict:
    return {
        "payment_id": str(payment.id),
        "booking_id": str(payment.booking_id),
        "user_id": str(payment.user_id),
        "amount": f"{payment.amount:.2f}",
        "currency": payment.currency,
        "status": payment.status,
        **extra,
    }


class PaymentProcessor:
    def __init__(self, session: AsyncSession, provider: FakePaymentProvider) -> None:
        self.session = session
        self.provider = provider

    async def _by_booking(self, booking_id: uuid.UUID) -> Payment | None:
        return await self.session.scalar(select(Payment).where(Payment.booking_id == booking_id))

    async def on_booking_created(self, payload: dict) -> None:
        booking_id = uuid.UUID(payload["booking_id"])
        if await self._by_booking(booking_id) is not None:
            logger.info("Payment already exists for booking", extra={"booking_id": str(booking_id)})
            return

        payment = Payment(
            id=uuid.uuid4(),
            booking_id=booking_id,
            user_id=uuid.UUID(payload["user_id"]),
            amount=Decimal(payload["amount"]),
            currency=payload.get("currency", "MDL"),
            status=PENDING,
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        self.session.add(payment)

        result = await self.provider.charge(payment.amount, payment.currency, reference=str(booking_id))
        payment.updated_at = utcnow()
        if result.success:
            payment.status = SUCCEEDED
            payment.provider_reference = result.reference
            add_outbox_event(self.session, OutboxEvent, "payment.succeeded", payment_event(payment))
            logger.info("Payment succeeded", extra={"payment_id": str(payment.id), "booking_id": str(booking_id)})
        else:
            payment.status = FAILED
            payment.failure_reason = result.reason
            add_outbox_event(self.session, OutboxEvent, "payment.failed", payment_event(payment, reason=result.reason))
            logger.info("Payment failed", extra={"payment_id": str(payment.id), "reason": result.reason})

    async def on_booking_cancelled(self, payload: dict) -> None:
        booking_id = uuid.UUID(payload["booking_id"])
        payment = await self._by_booking(booking_id)
        if payment is None:
            # Cancelled before booking.created was processed: remember it so we never charge later.
            self.session.add(
                Payment(
                    id=uuid.uuid4(), booking_id=booking_id, user_id=uuid.UUID(payload["user_id"]),
                    amount=Decimal(payload.get("amount", "0")), currency=payload.get("currency", "MDL"),
                    status=CANCELLED, failure_reason="booking_cancelled", created_at=utcnow(), updated_at=utcnow(),
                )
            )
            return
        if payment.status == SUCCEEDED:
            await self.provider.refund(payment.provider_reference or "", payment.amount)
            payment.status = REFUNDED
            payment.updated_at = utcnow()
            add_outbox_event(self.session, OutboxEvent, "payment.refunded", payment_event(payment))
            logger.info("Payment refunded", extra={"payment_id": str(payment.id)})
