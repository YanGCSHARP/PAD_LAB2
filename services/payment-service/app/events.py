from common.db import Database
from common.messaging import EventEnvelope, EventRouter
from common.outbox import claim_event

from .models import ProcessedEvent
from .provider import FakePaymentProvider
from .service import PaymentProcessor


def build_event_router(db: Database, provider: FakePaymentProvider) -> EventRouter:
    async def handle(event: EventEnvelope, action: str) -> None:
        async with db.sessionmaker() as session:
            if not await claim_event(session, ProcessedEvent, event):
                return
            await getattr(PaymentProcessor(session, provider), action)(event.payload)
            await session.commit()

    router = EventRouter()
    router.on("booking.created", lambda e: handle(e, "on_booking_created"))
    router.on("booking.cancelled", lambda e: handle(e, "on_booking_cancelled"))
    return router
