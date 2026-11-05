import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from common.app import create_base_app
from common.db import Database
from common.log import setup_logging
from common.messaging import EventBus
from common.security import JWTVerifier

from .api import router
from .config import Settings
from .events import build_event_router

logger = logging.getLogger(__name__)

DESCRIPTION = """
**User Service** — профили пользователей.

* Профиль создаётся асинхронно по событию `user.registered` (RabbitMQ), роль обновляется по `user.role_changed`.
* Обработка событий идемпотентна (таблица `processed_events`).
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.service_name, settings.log_level)

    db = Database(settings.database_url)
    bus = EventBus(settings.rabbitmq_url, settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await bus.connect()
        events = build_event_router(db)
        await bus.subscribe(settings.events_queue, events.routing_keys, events)
        logger.info("Service started")
        yield
        await bus.close()
        await db.dispose()

    app = create_base_app(
        service_name=settings.service_name,
        title="User Service",
        description=DESCRIPTION,
        version=settings.service_version,
        lifespan=lifespan,
        readiness_checks={"database": db.ping, "rabbitmq": bus.ping},
    )
    app.state.settings = settings
    app.state.db = db
    app.state.bus = bus
    app.state.verifier = JWTVerifier(settings.jwks_url)
    app.include_router(router)
    return app
