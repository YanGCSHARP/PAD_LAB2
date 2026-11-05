from common.db import Database
from common.messaging import EventEnvelope, EventRouter
from common.outbox import claim_event

from .catalog_client import CatalogGateway
from .models import ProcessedEvent
from .service import SagaHandlers


def build_event_router(db: Database, catalog: CatalogGateway) -> EventRouter:
    async def handle(event: EventEnvelope, action: str) -> None:
        async with db.sessionmaker() as session:
            if not await claim_event(session, ProcessedEvent, event):
                return
            await getattr(SagaHandlers(session, catalog), action)(event.payload)
            await session.commit()  # status change + outbox event + processed marker in ONE transaction

    router = EventRouter()
    router.on("payment.succeeded", lambda e: handle(e, "payment_succeeded"))
    router.on("payment.failed", lambda e: handle(e, "payment_failed"))
    return router
