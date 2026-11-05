import uuid

from conftest import login, register
from sqlalchemy import update

from app.models import User
from common.security import JWTVerifier


async def test_health_and_request_id(client):
    response = await client.get("/health", headers={"X-Request-ID": "req-123"})
    assert response.status_code == 200
    assert response.json()["service"] == "auth-service"
    assert response.headers["X-Request-ID"] == "req-123"


async def test_register_creates_user_and_outbox_event(client, outbox):
    response = await register(client, email="Alice@Example.com")
    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert body["role"] == "user"
    assert "password" not in str(body)

    events = await outbox()
    assert [e.event_type for e in events] == ["user.registered"]
    assert events[0].payload["user_id"] == body["id"]


async def test_register_duplicate_email_returns_409(client):
    await register(client)
    response = await register(client)
    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "email_taken"
    assert error["request_id"]


async def test_register_validation_errors(client):
    response = await client.post("/api/auth/register", json={"email": "not-an-email", "password": "short", "full_name": ""})
    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    fields = {d["field"] for d in error["details"]}
    assert {"email", "password", "full_name"} <= fields


async def test_password_must_contain_digits(client):
    response = await register(client, password="onlyletters")
    assert response.status_code == 422


async def test_login_and_me(client, app):
    await register(client)
    response = await login(client)
    assert response.status_code == 200
    tokens = response.json()
    assert tokens["token_type"] == "bearer"

    me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == "alice@example.com"


async def test_login_wrong_password(client):
    await register(client)
    response = await login(client, password="Wrong1234")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


async def test_login_disabled_account(client, app):
    await register(client)
    async with app.state.db.sessionmaker() as session:
        await session.execute(update(User).values(is_active=False))
        await session.commit()
    response = await login(client)
    assert response.status_code == 403


async def test_me_requires_token(client):
    response = await client.get("/api/auth/me")
    assert response.status_code == 401
    response = await client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


async def test_refresh_rotation(client):
    await register(client)
    tokens = (await login(client)).json()

    refreshed = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != tokens["refresh_token"]

    reused = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert reused.status_code == 401
    assert reused.json()["error"]["code"] == "invalid_refresh_token"


async def test_logout_revokes_refresh_token(client):
    await register(client)
    tokens = (await login(client)).json()
    assert (await client.post("/api/auth/logout", json={"refresh_token": tokens["refresh_token"]})).status_code == 204
    response = await client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert response.status_code == 401


async def test_jwks_can_verify_issued_token(client, app):
    await register(client)
    tokens = (await login(client)).json()
    jwks = (await client.get("/api/auth/.well-known/jwks.json")).json()
    assert jwks["keys"][0]["alg"] == "RS256"

    import json

    from jwt.algorithms import RSAAlgorithm

    key = RSAAlgorithm.from_jwk(json.dumps(jwks["keys"][0]))
    principal = await JWTVerifier(static_keys={jwks["keys"][0]["kid"]: key}).verify(tokens["access_token"])
    assert principal.email == "alice@example.com"
    assert principal.role == "user"


async def test_change_role_requires_admin(client, app, outbox):
    user = (await register(client)).json()
    user_token = (await login(client)).json()["access_token"]
    response = await client.patch(
        f"/api/auth/users/{user['id']}/role", json={"role": "admin"}, headers={"Authorization": f"Bearer {user_token}"}
    )
    assert response.status_code == 403

    admin_token = app.state.signer.access_token(user_id=str(uuid.uuid4()), role="admin", email="a@b.io", ttl_seconds=60)
    response = await client.patch(
        f"/api/auth/users/{user['id']}/role", json={"role": "admin"}, headers={"Authorization": f"Bearer {admin_token}"}
    )
    assert response.status_code == 200
    assert response.json()["role"] == "admin"
    assert (await outbox())[-1].event_type == "user.role_changed"


async def test_unknown_route_uses_error_envelope(client):
    response = await client.get("/api/auth/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
