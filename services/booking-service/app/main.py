import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from common.app import create_base_app
from common.db import Database
from common.log import setup_logging
from common.messaging import EventBus
from common.outbox import OutboxRelay
from common.resilience import CircuitBreaker
from common.security import JWTVerifier

from .api import router
from .catalog_client import CatalogGrpcClient
from .config import Settings
from .events import build_event_router
from .models import OutboxEvent

logger = logging.getLogger(__name__)

DESCRIPTION = """
**Booking Service** — бронирования билетов, оркестрация процесса покупки.

1. `POST /api/bookings` → gRPC `ReserveTickets` в catalog-service → бронь `PENDING_PAYMENT` + событие `booking.created`.
2. payment-service списывает деньги → `payment.succeeded` / `payment.failed`.
3. booking-service подтверждает бронь (`ConfirmReservation`) или отменяет её и возвращает билеты (`ReleaseTickets`)
   → `booking.confirmed` / `booking.cancelled`.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.service_name, settings.log_level)

    db = Database(settings.database_url)
    bus = EventBus(settings.rabbitmq_url, settings.service_name)
    catalog = CatalogGrpcClient(
        settings.catalog_grpc_target,
        settings.catalog_grpc_timeout_seconds,
        CircuitBreaker("catalog-grpc", settings.catalog_circuit_failure_threshold, settings.catalog_circuit_reset_seconds),
    )
    relay = OutboxRelay(db, OutboxEvent, bus, interval=settings.outbox_poll_interval)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await bus.connect()
        events = build_event_router(db, app.state.catalog)
        await bus.subscribe(settings.events_queue, events.routing_keys, events)
        relay.start()
        logger.info("Service started")
        yield
        await relay.stop()
        await bus.close()
        await app.state.catalog.close()
        await db.dispose()

    app = create_base_app(
        service_name=settings.service_name,
        title="Booking Service",
        description=DESCRIPTION,
        version=settings.service_version,
        lifespan=lifespan,
        readiness_checks={"database": db.ping, "rabbitmq": bus.ping},
    )
    app.state.settings = settings
    app.state.db = db
    app.state.bus = bus
    app.state.catalog = catalog
    app.state.verifier = JWTVerifier(settings.jwks_url)
    app.include_router(router)
    return app
