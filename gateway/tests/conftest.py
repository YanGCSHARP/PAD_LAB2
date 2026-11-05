from collections.abc import Callable

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.main import create_app
from app.ratelimit import InMemoryRateLimiter
from common.testing import TokenFactory

Handler = Callable[[httpx.Request], httpx.Response]


class FakeBackends:
    """Routes requests by upstream host to per-service handlers and records them."""

    def __init__(self) -> None:
        self.handlers: dict[str, Handler] = {}
        self.requests: list[httpx.Request] = []

    def on(self, service: str, handler: Handler) -> None:
        self.handlers[f"{service}-service"] = handler

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        handler = self.handlers.get(request.url.host)
        if handler is None:
            return httpx.Response(200, json={"service": request.url.host, "path": request.url.path})
        return handler(request)


@pytest.fixture
def tokens() -> TokenFactory:
    return TokenFactory()


@pytest.fixture
def backends() -> FakeBackends:
    return FakeBackends()


@pytest.fixture
def settings() -> Settings:
    return Settings(rate_limit_per_minute=1000, login_rate_limit_per_minute=3, upstream_retries=1,
                    circuit_failure_threshold=3, circuit_reset_seconds=60, upstream_timeout_seconds=1)


@pytest.fixture
async def client(settings, backends, tokens):
    app = create_app(
        settings,
        transport=httpx.MockTransport(backends),
        rate_limiter=InMemoryRateLimiter(),
        verifier=tokens.verifier(),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://gateway") as c:
        c.app = app  # type: ignore[attr-defined]
        yield c
