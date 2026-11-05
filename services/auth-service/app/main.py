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
from .crypto import TokenSigner, load_or_create_private_key
from .models import OutboxEvent
from .service import ensure_admin

logger = logging.getLogger(__name__)

DESCRIPTION = """
**Auth Service** — регистрация, аутентификация и выдача JWT.

* Access token: JWT RS256 (15 мин), публичный ключ доступен через JWKS.
* Refresh token: непрозрачная строка, хранится в БД в виде SHA-256, одноразовая (rotation).
* Публикует события `user.registered`, `user.role_changed` (через transactional outbox).
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.service_name, settings.log_level)

    db = Database(settings.database_url)
    bus = EventBus(settings.rabbitmq_url, settings.service_name)
    signer = TokenSigner(load_or_create_private_key(settings.jwt_private_key_path))
    relay = OutboxRelay(db, OutboxEvent, bus, interval=settings.outbox_poll_interval)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await bus.connect()
        await ensure_admin(db, settings, signer)
        relay.start()
        logger.info("Service started")
        yield
        await relay.stop()
        await bus.close()
        await db.dispose()
        logger.info("Service stopped")

    app = create_base_app(
        service_name=settings.service_name,
        title="Auth Service",
        description=DESCRIPTION,
        version=settings.service_version,
        lifespan=lifespan,
        readiness_checks={"database": db.ping, "rabbitmq": bus.ping},
    )
    app.state.settings = settings
    app.state.db = db
    app.state.bus = bus
    app.state.signer = signer
    # auth-service verifies its own tokens with the in-memory public key (no HTTP round trip).
    app.state.verifier = JWTVerifier(static_keys={signer.kid: signer.public_key})
    app.include_router(router)
    return app
