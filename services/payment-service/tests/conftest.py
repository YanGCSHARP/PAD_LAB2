import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.events import build_event_router
from app.main import create_app
from app.models import Base, OutboxEvent
from common.testing import InMemoryBus, TokenFactory


@pytest.fixture
def tokens() -> TokenFactory:
    return TokenFactory()


@pytest.fixture
async def app(tmp_path, tokens):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'payment.db').as_posix()}",
        provider_latency_ms=0,
        decline_above_amount="1000.00",
    )
    application = create_app(settings)
    await application.state.db.create_all(Base.metadata)
    application.state.bus = InMemoryBus()
    application.state.verifier = tokens.verifier()
    yield application
    await application.state.db.dispose()


@pytest.fixture
def events(app):
    return build_event_router(app.state.db, app.state.provider)


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
