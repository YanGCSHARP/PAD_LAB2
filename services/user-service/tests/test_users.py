import uuid

import pytest

from app.events import on_user_registered, on_user_role_changed
from common.testing import make_envelope


def registered(user_id: uuid.UUID, email: str = "bob@example.com"):
    return make_envelope("user.registered", {"user_id": str(user_id), "email": email, "full_name": "Bob", "role": "user"})


async def test_profile_created_from_event(app, client, tokens):
    user_id = uuid.uuid4()
    await on_user_registered(app.state.db, registered(user_id))

    response = await client.get("/api/users/me", headers=tokens.headers(user_id))
    assert response.status_code == 200
    assert response.json()["email"] == "bob@example.com"


async def test_duplicate_event_is_idempotent(app, client, tokens):
    user_id = uuid.uuid4()
    event = registered(user_id)
    await on_user_registered(app.state.db, event)
    await on_user_registered(app.state.db, event)  # redelivery

    admin = tokens.headers(role="admin")
    response = await client.get("/api/users", headers=admin)
    assert response.json()["total"] == 1


async def test_me_not_provisioned_yet(client, tokens):
    response = await client.get("/api/users/me", headers=tokens.headers())
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "profile_not_found"


async def test_update_profile(app, client, tokens):
    user_id = uuid.uuid4()
    await on_user_registered(app.state.db, registered(user_id))
    response = await client.patch(
        "/api/users/me", json={"phone": "+37369123456", "city": "Chisinau"}, headers=tokens.headers(user_id)
    )
    assert response.status_code == 200
    assert response.json()["city"] == "Chisinau"
    assert response.json()["full_name"] == "Bob"


async def test_update_profile_validation(app, client, tokens):
    user_id = uuid.uuid4()
    await on_user_registered(app.state.db, registered(user_id))
    response = await client.patch("/api/users/me", json={"phone": "call me"}, headers=tokens.headers(user_id))
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "phone"


async def test_cannot_read_foreign_profile(app, client, tokens):
    owner = uuid.uuid4()
    await on_user_registered(app.state.db, registered(owner))
    response = await client.get(f"/api/users/{owner}", headers=tokens.headers())
    assert response.status_code == 403
    response = await client.get(f"/api/users/{owner}", headers=tokens.headers(role="admin"))
    assert response.status_code == 200


async def test_list_requires_admin(client, tokens):
    assert (await client.get("/api/users", headers=tokens.headers())).status_code == 403
    assert (await client.get("/api/users")).status_code == 401


async def test_role_change_event(app, client, tokens):
    user_id = uuid.uuid4()
    await on_user_registered(app.state.db, registered(user_id))
    await on_user_role_changed(app.state.db, make_envelope("user.role_changed", {"user_id": str(user_id), "role": "admin"}))
    response = await client.get("/api/users/me", headers=tokens.headers(user_id))
    assert response.json()["role"] == "admin"


async def test_role_change_before_profile_fails_for_retry(app):
    with pytest.raises(LookupError):
        await on_user_role_changed(app.state.db, make_envelope("user.role_changed", {"user_id": str(uuid.uuid4()), "role": "admin"}))
