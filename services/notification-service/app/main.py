import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from common.app import create_base_app
from common.log import setup_logging
from common.messaging import EventBus
from common.security import JWTVerifier

from .api import router
from .config import Settings
from .notifier import EmailSender, Notifier, build_event_router
from .repository import MongoNotificationRepository

logger = logging.getLogger(__name__)

DESCRIPTION = """
**Notification Service** — уведомления пользователей (MongoDB).

* Подписан на `user.registered`, `booking.*`, `payment.failed`, `payment.refunded`.
* Хранит локальную проекцию контактов пользователей (из `user.registered`) — не ходит синхронно в другие сервисы.
* Идемпотентность: уникальный индекс по `event_id`.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.service_name, settings.log_level)

    repo = MongoNotificationRepository(settings.mongo_url, settings.mongo_db)
    bus = EventBus(settings.rabbitmq_url, settings.service_name)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await repo.init()
        await bus.connect()
        events = build_event_router(Notifier(app.state.repo, EmailSender()))
        await bus.subscribe(settings.events_queue, events.routing_keys, events)
        logger.info("Service started")
        yield
        await bus.close()
        await repo.close()

    app = create_base_app(
        service_name=settings.service_name,
        title="Notification Service",
        description=DESCRIPTION,
        version=settings.service_version,
        lifespan=lifespan,
        readiness_checks={"mongodb": lambda: app.state.repo.ping(), "rabbitmq": bus.ping},
    )
    app.state.settings = settings
    app.state.repo = repo
    app.state.bus = bus
    app.state.verifier = JWTVerifier(settings.jwks_url)
    app.include_router(router)
    return app
