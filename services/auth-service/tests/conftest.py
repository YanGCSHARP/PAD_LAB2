import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import Base, OutboxEvent
from common.testing import InMemoryBus


@pytest.fixture
async def app(tmp_path):
    settings = Settings(
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'auth.db').as_posix()}",
        jwt_private_key_path=str(tmp_path / "key.pem"),
        bcrypt_rounds=4,
        admin_password=None,
    )
    application = create_app(settings)
    await application.state.db.create_all(Base.metadata)
    application.state.bus = InMemoryBus()
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


async def register(client, email="alice@example.com", password="Secret123", full_name="Alice"):
    return await client.post("/api/auth/register", json={"email": email, "password": password, "full_name": full_name})


async def login(client, email="alice@example.com", password="Secret123"):
    return await client.post("/api/auth/login", json={"email": email, "password": password})
