import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.notifier import EmailSender, Notifier, build_event_router
from app.repository import InMemoryNotificationRepository
from common.testing import TokenFactory


class RecordingSender(EmailSender):
    def __init__(self) -> None:
        self.sent: list[tuple[str | None, str]] = []
        self.fail = False

    async def send(self, to, subject, body):
        if self.fail:
            raise ConnectionError("SMTP down")
        self.sent.append((to, subject))


@pytest.fixture
def tokens() -> TokenFactory:
    return TokenFactory()


@pytest.fixture
def repo() -> InMemoryNotificationRepository:
    return InMemoryNotificationRepository()


@pytest.fixture
def sender() -> RecordingSender:
    return RecordingSender()


@pytest.fixture
def events(repo, sender):
    return build_event_router(Notifier(repo, sender))


@pytest.fixture
async def client(repo, tokens):
    app = create_app(Settings())
    app.state.repo = repo
    app.state.verifier = tokens.verifier()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
