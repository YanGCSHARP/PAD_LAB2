import uuid

from conftest import SOLD_OUT, STANDARD

from app.events import build_event_router
from common.testing import make_envelope


async def book(client, headers, category=STANDARD, quantity=2, **extra_headers):
    return await client.post("/api/bookings", json={"category_id": str(category), "quantity": quantity}, headers={**headers, **extra_headers})


async def test_create_booking_reserves_and_emits_event(client, tokens, catalog, outbox):
    user_id = uuid.uuid4()
    response = await book(client, tokens.headers(user_id, email="bob@example.com"))
    assert response.status_code == 201
    booking = response.json()
    assert booking["status"] == "PENDING_PAYMENT"
    assert booking["total_amount"] == "500.00"
    assert uuid.UUID(booking["id"]) in catalog.reserved

    events = await outbox()
    assert [e.event_type for e in events] == ["booking.created"]
    assert events[0].payload["amount"] == "500.00"
    assert events[0].payload["user_email"] == "bob@example.com"


async def test_validation_errors(client, tokens):
    response = await book(client, tokens.headers(), quantity=0)
    assert response.status_code == 422
    response = await client.post("/api/bookings", json={"category_id": "x", "quantity": 1}, headers=tokens.headers())
    assert response.status_code == 422


async def test_requires_authentication(client):
    assert (await client.get("/api/bookings")).status_code == 401


async def test_sold_out_and_unknown_category(client, tokens):
    response = await book(client, tokens.headers(), category=SOLD_OUT)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "sold_out"
    response = await book(client, tokens.headers(), category=uuid.uuid4())
    assert response.status_code == 404


async def test_catalog_down_returns_503(client, tokens, catalog, outbox):
    catalog.down = True
    response = await book(client, tokens.headers())
    assert response.status_code == 503
    assert await outbox() == []


async def test_idempotency_key(client, tokens, catalog):
    headers = tokens.headers(uuid.uuid4())
    first = await book(client, headers, **{"Idempotency-Key": "abc"})
    second = await book(client, headers, **{"Idempotency-Key": "abc"})
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert len(catalog.reserved) == 1


async def test_users_see_only_their_bookings(client, tokens):
    alice, bob = uuid.uuid4(), uuid.uuid4()
    booking = (await book(client, tokens.headers(alice))).json()
    await book(client, tokens.headers(bob))

    assert (await client.get("/api/bookings", headers=tokens.headers(alice))).json()["total"] == 1
    assert (await client.get(f"/api/bookings/{booking['id']}", headers=tokens.headers(bob))).status_code == 404
    assert (await client.get("/api/bookings", headers=tokens.headers(role="admin"))).json()["total"] == 2


async def test_cancel_booking(client, tokens, catalog, outbox):
    headers = tokens.headers(uuid.uuid4())
    booking = (await book(client, headers)).json()
    response = await client.post(f"/api/bookings/{booking['id']}/cancel", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "CANCELLED"
    assert uuid.UUID(booking["id"]) in catalog.released
    assert (await outbox())[-1].event_type == "booking.cancelled"

    again = await client.post(f"/api/bookings/{booking['id']}/cancel", headers=headers)
    assert again.status_code == 409


async def test_saga_payment_succeeded(app, client, tokens, catalog, outbox):
    headers = tokens.headers(uuid.uuid4())
    booking = (await book(client, headers)).json()
    router = build_event_router(app.state.db, catalog)

    event = make_envelope("payment.succeeded", {"booking_id": booking["id"], "payment_id": str(uuid.uuid4())})
    await router(event)
    await router(event)  # duplicate delivery is ignored

    current = (await client.get(f"/api/bookings/{booking['id']}", headers=headers)).json()
    assert current["status"] == "CONFIRMED"
    assert uuid.UUID(booking["id"]) in catalog.confirmed
    assert [e.event_type for e in await outbox()] == ["booking.created", "booking.confirmed"]


async def test_saga_payment_failed_compensates(app, client, tokens, catalog, outbox):
    headers = tokens.headers(uuid.uuid4())
    booking = (await book(client, headers)).json()
    router = build_event_router(app.state.db, catalog)
    await router(make_envelope("payment.failed", {"booking_id": booking["id"], "reason": "insufficient_funds"}))

    current = (await client.get(f"/api/bookings/{booking['id']}", headers=headers)).json()
    assert current["status"] == "CANCELLED"
    assert current["cancel_reason"] == "payment_failed: insufficient_funds"
    assert uuid.UUID(booking["id"]) in catalog.released
    assert (await outbox())[-1].payload["reason"] == "payment_failed: insufficient_funds"


async def test_payment_after_user_cancel_is_ignored(app, client, tokens, catalog):
    headers = tokens.headers(uuid.uuid4())
    booking = (await book(client, headers)).json()
    await client.post(f"/api/bookings/{booking['id']}/cancel", headers=headers)
    router = build_event_router(app.state.db, catalog)
    await router(make_envelope("payment.succeeded", {"booking_id": booking["id"], "payment_id": str(uuid.uuid4())}))
    current = (await client.get(f"/api/bookings/{booking['id']}", headers=headers)).json()
    assert current["status"] == "CANCELLED"


async def test_handler_failure_is_not_marked_processed(app, client, tokens, catalog):
    """If catalog is down while confirming, the handler raises (-> broker retry) and nothing is committed."""
    headers = tokens.headers(uuid.uuid4())
    booking = (await book(client, headers)).json()
    router = build_event_router(app.state.db, catalog)
    event = make_envelope("payment.failed", {"booking_id": booking["id"], "reason": "declined"})

    catalog.down = True
    try:
        await router(event)
    except Exception:
        pass
    assert (await client.get(f"/api/bookings/{booking['id']}", headers=headers)).json()["status"] == "PENDING_PAYMENT"

    catalog.down = False
    await router(event)  # retry succeeds
    assert (await client.get(f"/api/bookings/{booking['id']}", headers=headers)).json()["status"] == "CANCELLED"
