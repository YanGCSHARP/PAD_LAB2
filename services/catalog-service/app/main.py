import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from common.app import create_base_app
from common.db import Database
from common.log import setup_logging
from common.security import JWTVerifier

from .api import router
from .config import Settings
from .grpc_server import start_grpc_server
from .seed import seed_demo_data

logger = logging.getLogger(__name__)

DESCRIPTION = """
**Catalog Service** — площадки, мероприятия, категории билетов и их остатки.

* REST API (публичное чтение, изменение — только `admin`).
* gRPC API `CatalogReservation` (порт 50051) для booking-service: резерв / подтверждение / освобождение билетов.
  Резерв — атомарный условный `UPDATE ... WHERE available >= qty`, поэтому овербукинг невозможен.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.service_name, settings.log_level)
    db = Database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.seed_demo_data:
            await seed_demo_data(db)
        grpc_server, _ = await start_grpc_server(db, f"[::]:{settings.grpc_port}")
        logger.info("Service started")
        yield
        await grpc_server.stop(grace=5)
        await db.dispose()

    app = create_base_app(
        service_name=settings.service_name,
        title="Catalog Service",
        description=DESCRIPTION,
        version=settings.service_version,
        lifespan=lifespan,
        readiness_checks={"database": db.ping},
    )
    app.state.settings = settings
    app.state.db = db
    app.state.verifier = JWTVerifier(settings.jwks_url)
    app.include_router(router)
    return app
