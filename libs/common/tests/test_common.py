import json
import logging
import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from common.app import create_base_app
from common.errors import NotFoundError
from common.log import JsonFormatter, request_id_ctx
from common.messaging import EventEnvelope, EventRouter
from common.resilience import CircuitBreaker
from common.security import JWTVerifier, encode_token
from common.testing import TokenFactory, generate_private_key


# ------------------------------------------------------------------ logging
def test_json_log_contains_required_fields():
    token = request_id_ctx.set("rid-42")
    try:
        record = logging.LogRecord("svc", logging.INFO, __file__, 1, "Order %s", ("created",), None)
        record.order_id = "o-1"
        entry = json.loads(JsonFormatter("order-service").format(record))
    finally:
        request_id_ctx.reset(token)
    assert entry["service"] == "order-service"
    assert entry["level"] == "INFO"
    assert entry["request_id"] == "rid-42"
    assert entry["message"] == "Order created"
    assert entry["order_id"] == "o-1"
    assert entry["timestamp"].endswith("Z")


# ------------------------------------------------------------------ errors / health / middleware
def make_app(ready: bool = True) -> FastAPI:
    async def check():
        if not ready:
            raise ConnectionError("db down")

    app = create_base_app(service_name="demo", title="Demo", description="", version="1", lifespan=None, readiness_checks={"db": check})

    @app.get("/items/{item_id}")
    async def item(item_id: int):
        if item_id == 0:
            raise NotFoundError("Item not found")
        if item_id == 500:
            raise RuntimeError("secret internal detail")
        return {"id": item_id}

    return app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=make_app()), base_url="http://t") as c:
        yield c


async def test_not_found_error_envelope(client):
    response = await client.get("/items/0", headers={"X-Request-ID": "abc"})
    assert response.status_code == 404
    assert response.json() == {"error": {"code": "not_found", "message": "Item not found", "request_id": "abc"}}
    assert response.headers["X-Request-ID"] == "abc"


async def test_unhandled_exception_hides_stack_trace(client):
    response = await client.get("/items/500")
    assert response.status_code == 500
    body = response.text
    assert "secret internal detail" not in body and "Traceback" not in body
    assert response.json()["error"]["code"] == "internal_error"


async def test_validation_error_envelope(client):
    response = await client.get("/items/abc")
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "item_id"


async def test_request_id_generated_when_missing(client):
    response = await client.get("/health")
    assert len(response.headers["X-Request-ID"]) == 32


async def test_readiness_reports_failed_dependency():
    async with AsyncClient(transport=ASGITransport(app=make_app(ready=False)), base_url="http://t") as c:
        response = await c.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"] == {"db": "error: ConnectionError"}


async def test_metrics_endpoint(client):
    await client.get("/items/1")
    text = (await client.get("/metrics")).text
    assert 'http_requests_total{method="GET",path="/items/{item_id}",status="200"}' in text


# ------------------------------------------------------------------ security
async def test_token_roundtrip_and_failures():
    tokens = TokenFactory()
    user_id = uuid.uuid4()
    principal = await tokens.verifier().verify(tokens.token(user_id, role="admin"))
    assert principal.user_id == user_id and principal.is_admin

    from common.errors import UnauthorizedError

    with pytest.raises(UnauthorizedError) as exc:
        await tokens.verifier().verify(tokens.token(ttl=-10))
    assert exc.value.code == "token_expired"

    foreign_key = generate_private_key()
    forged = encode_token(foreign_key, "test-key", subject=str(user_id), role="admin", email=None)
    with pytest.raises(UnauthorizedError):
        await tokens.verifier().verify(forged)

    refresh_like = encode_token(tokens.private_key, "test-key", subject=str(user_id), role="user", email=None, token_type="refresh")
    with pytest.raises(UnauthorizedError):
        await tokens.verifier().verify(refresh_like)


async def test_unknown_kid_without_jwks_is_rejected():
    tokens = TokenFactory()
    from common.errors import UnauthorizedError

    with pytest.raises(UnauthorizedError):
        await JWTVerifier(static_keys={}).verify(tokens.token())


# ------------------------------------------------------------------ resilience / messaging
def test_circuit_breaker_transitions(monkeypatch):
    now = [100.0]
    monkeypatch.setattr("common.resilience.time.monotonic", lambda: now[0])
    breaker = CircuitBreaker("x", failure_threshold=2, reset_timeout=10)
    breaker.record_failure()
    assert breaker.allow_request()
    breaker.record_failure()
    assert breaker.state == "open" and not breaker.allow_request()
    now[0] += 11
    assert breaker.allow_request() and breaker.state == "half_open"
    breaker.record_failure()
    assert breaker.state == "open"
    now[0] += 11
    breaker.allow_request()
    breaker.record_success()
    assert breaker.state == "closed"


def test_envelope_parse():
    raw = json.dumps({"event_id": "1", "event_type": "a.b", "payload": {"x": 1}}).encode()
    envelope = EventEnvelope.parse(raw)
    assert envelope.event_type == "a.b" and envelope.payload == {"x": 1}
    with pytest.raises((ValueError, KeyError)):
        EventEnvelope.parse(b"not json")


async def test_event_router_dispatch():
    seen = []
    router = EventRouter()

    async def handler(env):
        seen.append(env.event_type)

    router.on("a.created", handler)
    await router(EventEnvelope("1", "a.created", "", "t", {}))
    await router(EventEnvelope("2", "unknown", "", "t", {}))
    assert seen == ["a.created"]
    assert router.routing_keys == ["a.created"]
