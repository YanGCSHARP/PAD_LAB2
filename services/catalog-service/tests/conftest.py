import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.models import Base
from common.testing import TokenFactory


@pytest.fixture
def tokens() -> TokenFactory:
    return TokenFactory()


@pytest.fixture
async def app(tmp_path, tokens):
    settings = Settings(database_url=f"sqlite+aiosqlite:///{(tmp_path / 'catalog.db').as_posix()}", seed_demo_data=False)
    application = create_app(settings)
    await application.state.db.create_all(Base.metadata)
    application.state.verifier = tokens.verifier()
    yield application
    await application.state.db.dispose()


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def admin(tokens):
    return tokens.headers(uuid.uuid4(), role="admin")


@pytest.fixture
async def event(client, admin):
    """Creates a venue + event with two categories ("Standard": 10 tickets, "VIP": 2 tickets)."""
    venue = (await client.post("/api/venues", json={"name": "Hall", "city": "Chisinau", "address": "Main 1", "capacity": 100}, headers=admin)).json()
    payload = {
        "venue_id": venue["id"],
        "title": "Jazz Night",
        "description": "Live jazz",
        "starts_at": (datetime.now(UTC) + timedelta(days=10)).isoformat(),
        "ticket_categories": [{"name": "Standard", "price": "100.00", "total": 10}, {"name": "VIP", "price": "500.00", "total": 2}],
    }
    response = await client.post("/api/events", json=payload, headers=admin)
    assert response.status_code == 201, response.text
    return response.json()


def category(event: dict, name: str) -> dict:
    return next(c for c in event["ticket_categories"] if c["name"] == name)
