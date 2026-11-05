import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.catalog_client import Reservation
from app.config import Settings
from app.main import create_app
from app.models import Base, OutboxEvent
from common.errors import ConflictError, NotFoundError, ServiceUnavailableError
from common.testing import InMemoryBus, TokenFactory

STANDARD = uuid.UUID("00000000-0000-0000-0000-00000000000a")
SOLD_OUT = uuid.UUID("00000000-0000-0000-0000-00000000000b")
EVENT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000e1")


class FakeCatalog:
    """In-memory stand-in for the catalog gRPC client."""

    def __init__(self) -> None:
        self.reserved: dict[uuid.UUID, int] = {}
        self.confirmed: set[uuid.UUID] = set()
        self.released: set[uuid.UUID] = set()
        self.down = False

    async def reserve(self, booking_id, category_id, quantity):
        if self.down:
            raise ServiceUnavailableError("Catalog service is unavailable")
        if category_id == SOLD_OUT:
            raise ConflictError("Not enough tickets available", code="sold_out")
        if category_id != STANDARD:
            raise NotFoundError("Ticket category not found", code="category_not_found")
        self.reserved[booking_id] = quantity
        price = Decimal("250.00")
        return Reservation(booking_id, EVENT_ID, "Rock Night", category_id, "Standard", quantity, price, price * quantity,
                           "reserved", datetime.now(UTC) + timedelta(days=5))

    async def confirm(self, booking_id):
        self.confirmed.add(booking_id)

    async def release(self, booking_id):
        if self.down:
            raise ServiceUnavailableError("Catalog service is unavailable")
        self.released.add(booking_id)

    async def close(self):
        pass


@pytest.fixture
def tokens() -> TokenFactory:
    return TokenFactory()


@pytest.fixture
def catalog() -> FakeCatalog:
    return FakeCatalog()


@pytest.fixture
async def app(tmp_path, tokens, catalog):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{(tmp_path / 'booking.db').as_posix()}")
    application = create_app(settings)
    await application.state.db.create_all(Base.metadata)
    application.state.bus = InMemoryBus()
    application.state.verifier = tokens.verifier()
    application.state.catalog = catalog
    yield application
    await application.state.db.dispose()


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def outbox(app):
    async def _read() -> list[OutboxEvent]:
        async with app.state.db.sessionmaker() as session:
            return list((await session.scalars(select(OutboxEvent).order_by(OutboxEvent.created_at))).all())

    return _read
