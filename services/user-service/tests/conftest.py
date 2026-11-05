import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.models import Base
from common.testing import InMemoryBus, TokenFactory


@pytest.fixture
def tokens() -> TokenFactory:
    return TokenFactory()


@pytest.fixture
async def app(tmp_path, tokens):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{(tmp_path / 'users.db').as_posix()}")
    application = create_app(settings)
    await application.state.db.create_all(Base.metadata)
    application.state.bus = InMemoryBus()
    application.state.verifier = tokens.verifier()
    yield application
    await application.state.db.dispose()


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
