import uuid

import httpx


async def test_public_route_is_forwarded_without_token(client, backends):
    response = await client.get("/api/events", params={"city": "Chisinau"})
    assert response.status_code == 200
    forwarded = backends.requests[-1]
    assert forwarded.url.host == "catalog-service"
    assert forwarded.url.params["city"] == "Chisinau"
    assert "x-user-id" not in forwarded.headers
    assert response.headers["X-RateLimit-Limit"] == "1000"


async def test_protected_route_requires_token(client, backends):
    response = await client.get("/api/bookings")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"
    assert backends.requests == []  # upstream never called


async def test_invalid_token_rejected(client):
    response = await client.get("/api/bookings", headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_authenticated_request_gets_identity_headers(client, backends, tokens):
    user_id = uuid.uuid4()
    response = await client.post(
        "/api/bookings", json={"quantity": 1}, headers={**tokens.headers(user_id), "Idempotency-Key": "k1", "X-Request-ID": "rid-1"}
    )
    assert response.status_code == 200
    forwarded = backends.requests[-1]
    assert forwarded.url.host == "booking-service"
    assert forwarded.headers["x-user-id"] == str(user_id)
    assert forwarded.headers["x-user-role"] == "user"
    assert forwarded.headers["idempotency-key"] == "k1"
    assert forwarded.headers["x-request-id"] == "rid-1"
    assert forwarded.headers["authorization"].startswith("Bearer ")
    assert response.headers["X-Request-ID"] == "rid-1"


async def test_admin_only_routes(client, tokens, backends):
    body = {"title": "x"}
    response = await client.post("/api/events", json=body, headers=tokens.headers(role="user"))
    assert response.status_code == 403
    response = await client.post("/api/events", json=body)
    assert response.status_code == 401
    response = await client.post("/api/events", json=body, headers=tokens.headers(role="admin"))
    assert response.status_code == 200
    assert backends.requests[-1].headers["x-user-role"] == "admin"


async def test_unknown_route_returns_404(client):
    response = await client.get("/api/unknown")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_upstream_error_status_is_passed_through(client, backends, tokens):
    backends.on("booking", lambda r: httpx.Response(409, json={"error": {"code": "sold_out", "message": "x", "request_id": "1"}}))
    response = await client.post("/api/bookings", json={}, headers=tokens.headers())
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "sold_out"


async def test_upstream_timeout_returns_504(client, backends):
    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    backends.on("catalog", timeout)
    response = await client.get("/api/events")
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "upstream_timeout"
    assert len(backends.requests) == 2  # GET is retried once


async def test_upstream_down_returns_503_and_opens_circuit(client, backends):
    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    backends.on("catalog", refused)
    first = await client.get("/api/events")
    assert first.status_code == 503
    second = await client.get("/api/events")  # 4 failures >= threshold 3 -> circuit opens
    assert second.status_code == 503
    calls = len(backends.requests)
    third = await client.get("/api/events")
    assert third.json()["error"]["code"] == "circuit_open"
    assert len(backends.requests) == calls  # short-circuited, upstream not called


async def test_post_is_not_retried(client, backends, tokens):
    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    backends.on("booking", refused)
    response = await client.post("/api/bookings", json={}, headers=tokens.headers())
    assert response.status_code == 503
    assert len(backends.requests) == 1


async def test_login_rate_limit(client):
    statuses = [
        (await client.post("/api/auth/login", json={"email": "a@b.c", "password": "x"})).status_code for _ in range(4)
    ]
    assert statuses[:3] == [200, 200, 200]
    assert statuses[3] == 429


async def test_rate_limit_response_has_retry_after(client):
    for _ in range(3):
        await client.post("/api/auth/login", json={})
    response = await client.post("/api/auth/login", json={})
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert response.json()["error"]["code"] == "rate_limited"


async def test_dashboard_aggregates_and_degrades(client, backends, tokens):
    backends.on("user", lambda r: httpx.Response(200, json={"full_name": "Alice"}))
    backends.on("booking", lambda r: httpx.Response(200, json={"items": [{"id": "b1"}], "total": 1}))
    backends.on("notification", lambda r: httpx.Response(500, json={}))

    response = await client.get("/api/dashboard", headers=tokens.headers())
    assert response.status_code == 200
    body = response.json()
    assert body["profile"]["full_name"] == "Alice"
    assert body["recent_bookings"] == [{"id": "b1"}]
    assert body["unread_notifications"] is None
    assert body["degraded"] == ["notification"]


async def test_dashboard_requires_auth(client):
    assert (await client.get("/api/dashboard")).status_code == 401


async def test_status_reports_each_service(client, backends):
    def refused(request):
        raise httpx.ConnectError("refused", request=request)

    backends.on("payment", refused)
    response = await client.get("/api/status")
    services = response.json()["services"]
    assert services["auth"]["status"] == "up"
    assert services["payment"]["status"] == "down"


async def test_docs_page_and_service_specs(client, backends):
    assert "swagger-ui" in (await client.get("/docs")).text
    backends.on("booking", lambda r: httpx.Response(200, json={"openapi": "3.1.0", "paths": {}}))
    response = await client.get("/openapi/booking.json")
    assert response.json()["openapi"] == "3.1.0"
