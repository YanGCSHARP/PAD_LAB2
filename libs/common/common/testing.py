"""Helpers for unit tests of the services (no RabbitMQ / Postgres / auth-service needed)."""

import uuid
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives.asymmetric import rsa

from .messaging import EventEnvelope
from .security import ROLE_USER, JWTVerifier, encode_token

TEST_KID = "test-key"


def generate_private_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


class TokenFactory:
    def __init__(self) -> None:
        self.private_key = generate_private_key()

    def verifier(self) -> JWTVerifier:
        return JWTVerifier(static_keys={TEST_KID: self.private_key.public_key()})

    def token(
        self, user_id: uuid.UUID | None = None, role: str = ROLE_USER, email: str = "user@example.com", ttl: int = 600
    ) -> str:
        return encode_token(
            self.private_key, TEST_KID, subject=str(user_id or uuid.uuid4()), role=role, email=email, ttl_seconds=ttl
        )

    def headers(self, user_id: uuid.UUID | None = None, role: str = ROLE_USER, email: str = "user@example.com") -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token(user_id, role, email)}"}


class InMemoryBus:
    """Drop-in replacement for EventBus that records published events."""

    def __init__(self) -> None:
        self.published: list[dict[str, Any]] = []
        self.is_connected = True

    async def connect(self, *args: Any, **kwargs: Any) -> None:
        return None

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def publish(self, event_type: str, payload: dict[str, Any], *, event_id: str | None = None,
                      request_id: str | None = None, occurred_at: datetime | None = None) -> None:
        self.published.append({"event_type": event_type, "payload": payload, "event_id": event_id or str(uuid.uuid4())})

    async def subscribe(self, *args: Any, **kwargs: Any) -> None:
        return None


def make_envelope(event_type: str, payload: dict[str, Any], event_id: str | None = None) -> EventEnvelope:
    return EventEnvelope(
        event_id=event_id or str(uuid.uuid4()),
        event_type=event_type,
        occurred_at=datetime.now().isoformat(),
        producer="test",
        payload=payload,
    )
