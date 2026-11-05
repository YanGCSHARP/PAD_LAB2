import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from common.app import create_base_app
from common.db import Database
from common.log import setup_logging
from common.messaging import EventBus
from common.outbox import OutboxRelay
from common.security import JWTVerifier

from .api import router
from .config import Settings
from .events import build_event_router
from .models import OutboxEvent
from .provider import FakePaymentProvider

logger = logging.getLogger(__name__)

DESCRIPTION = """
**Payment Service** — платежи по бронированиям (провайдер эмулируется).

* Слушает `booking.created` → списание → `payment.succeeded` / `payment.failed`.
* Слушает `booking.cancelled` → возврат (`payment.refunded`), если платёж уже прошёл.
* Сумма больше `DECLINE_ABOVE_AMOUNT` (по умолчанию 10000) отклоняется — чтобы продемонстрировать компенсацию саги.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.service_name, settings.log_level)

    db = Database(settings.database_url)
    bus = EventBus(settings.rabbitmq_url, settings.service_name)
    provider = FakePaymentProvider(settings.provider_latency_ms, settings.decline_above_amount)
    relay = OutboxRelay(db, OutboxEvent, bus, interval=settings.outbox_poll_interval)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await bus.connect()
        events = build_event_router(db, provider)
        await bus.subscribe(settings.events_queue, events.routing_keys, events, prefetch=5)
        relay.start()
        logger.info("Service started")
        yield
        await relay.stop()
        await bus.close()
        await db.dispose()

    app = create_base_app(
        service_name=settings.service_name,
        title="Payment Service",
        description=DESCRIPTION,
        version=settings.service_version,
        lifespan=lifespan,
        readiness_checks={"database": db.ping, "rabbitmq": bus.ping},
    )
    app.state.settings = settings
    app.state.db = db
    app.state.bus = bus
    app.state.provider = provider
    app.state.verifier = JWTVerifier(settings.jwks_url)
    app.include_router(router)
    return app
