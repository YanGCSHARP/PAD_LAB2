"""End-to-end tests against the running docker-compose stack (through the API Gateway).

    docker compose up -d --build --wait
    pytest tests/e2e
"""

import os
import time
import uuid
from collections.abc import Callable

import httpx
import pytest

GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:8080")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@ticketing.io")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Admin12345")


@pytest.fixture(scope="session")
def api() -> httpx.Client:
    with httpx.Client(base_url=GATEWAY_URL, timeout=15) as client:
        deadline = time.time() + 120
        while True:
            try:
                status = client.get("/api/status").json()
                if all(s["status"] == "up" for s in status["services"].values()):
                    break
            except (httpx.HTTPError, KeyError, ValueError):
                pass
            if time.time() > deadline:
                pytest.fail("Stack is not ready (GET /api/status)")
            time.sleep(2)
        yield client


def auth_headers(api: httpx.Client, email: str, password: str) -> dict[str, str]:
    response = api.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture(scope="session")
def admin(api) -> dict[str, str]:
    return auth_headers(api, ADMIN_EMAIL, ADMIN_PASSWORD)


@pytest.fixture
def user(api) -> tuple[dict[str, str], dict]:
    email = f"e2e-{uuid.uuid4().hex[:10]}@example.com"
    password = "Passw0rd123"
    registered = api.post("/api/auth/register", json={"email": email, "password": password, "full_name": "E2E User"})
    assert registered.status_code == 201, registered.text
    return auth_headers(api, email, password), registered.json()


def wait_for(predicate: Callable[[], object], timeout: float = 30, interval: float = 0.5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = predicate()
        if result:
            return result
        time.sleep(interval)
    raise AssertionError("condition not met in time")
