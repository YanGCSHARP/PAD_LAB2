import uuid

import pytest

from common.testing import make_envelope


def registered(user_id):
    return make_envelope("user.registered", {"user_id": str(user_id), "email": "eve@example.com", "full_name": "Eve"})


def booking(event_type, user_id, **extra):
    return make_envelope(event_type, {"user_id": str(user_id), "booking_id": str(uuid.uuid4()), "event_title": "Hamlet",
                                      "quantity": 2, "amount": "400.00", "currency": "MDL", **extra})


async def test_welcome_notification_and_contact_projection(events, repo, sender):
    user_id = uuid.uuid4()
    await events(registered(user_id))
    assert repo.contacts[str(user_id)]["email"] == "eve@example.com"
    assert sender.sent == [("eve@example.com", "Добро пожаловать!")]


async def test_booking_notifications_use_projected_email(events, sender):
    user_id = uuid.uuid4()
    await events(registered(user_id))
    await events(booking("booking.confirmed", user_id))
    assert sender.sent[-1] == ("eve@example.com", "Бронь подтверждена")


async def test_duplicate_event_sends_once(events, sender):
    event = booking("booking.created", uuid.uuid4(), user_email="x@example.com")
    await events(event)
    await events(event)
    assert len(sender.sent) == 1


async def test_failed_send_is_retried(events, sender, repo):
    event = booking("booking.cancelled", uuid.uuid4(), reason="payment_failed")
    sender.fail = True
    with pytest.raises(ConnectionError):
        await events(event)
    sender.fail = False
    await events(event)  # redelivery after failure -> email finally sent
    assert len(sender.sent) == 1
    assert len(repo.items) == 1


async def test_unrelated_event_ignored(events, sender):
    await events(make_envelope("payment.succeeded", {"user_id": str(uuid.uuid4())}))
    assert sender.sent == []


async def test_api_list_read_and_count(events, client, tokens):
    user_id = uuid.uuid4()
    await events(registered(user_id))
    await events(booking("booking.created", user_id))
    headers = tokens.headers(user_id)

    page = (await client.get("/api/notifications", headers=headers)).json()
    assert page["total"] == 2
    assert page["items"][0]["title"] == "Бронь создана"  # newest first
    assert (await client.get("/api/notifications/unread-count", headers=headers)).json() == {"count": 2}

    response = await client.post(f"/api/notifications/{page['items'][0]['id']}/read", headers=headers)
    assert response.json() == {"count": 1}
    unread = (await client.get("/api/notifications", params={"unread_only": True}, headers=headers)).json()
    assert unread["total"] == 1


async def test_cannot_read_foreign_notification(events, client, tokens):
    owner = uuid.uuid4()
    await events(registered(owner))
    item = (await client.get("/api/notifications", headers=tokens.headers(owner))).json()["items"][0]
    response = await client.post(f"/api/notifications/{item['id']}/read", headers=tokens.headers())
    assert response.status_code == 404
    assert (await client.get("/api/notifications")).status_code == 401
