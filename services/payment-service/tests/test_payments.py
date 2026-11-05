import uuid

from common.testing import make_envelope


def booking_created(user_id: uuid.UUID, amount: str = "500.00", booking_id: uuid.UUID | None = None):
    return make_envelope(
        "booking.created",
        {"booking_id": str(booking_id or uuid.uuid4()), "user_id": str(user_id), "amount": amount, "currency": "MDL"},
    )


def booking_cancelled(event):
    return make_envelope("booking.cancelled", {**event.payload, "reason": "cancelled_by_user"})


async def test_successful_payment(events, outbox, client, tokens):
    user_id = uuid.uuid4()
    event = booking_created(user_id)
    await events(event)

    emitted = await outbox()
    assert [e.event_type for e in emitted] == ["payment.succeeded"]
    assert emitted[0].payload["booking_id"] == event.payload["booking_id"]

    page = (await client.get("/api/payments", headers=tokens.headers(user_id))).json()
    assert page["total"] == 1
    assert page["items"][0]["status"] == "SUCCEEDED"
    assert page["items"][0]["provider_reference"].startswith("psp_")


async def test_declined_payment(events, outbox):
    await events(booking_created(uuid.uuid4(), amount="5000.00"))
    emitted = await outbox()
    assert emitted[0].event_type == "payment.failed"
    assert emitted[0].payload["reason"] == "insufficient_funds"


async def test_duplicate_and_redelivered_events(events, outbox):
    event = booking_created(uuid.uuid4())
    await events(event)
    await events(event)  # same event_id
    await events(make_envelope("booking.created", event.payload))  # new event_id, same booking
    assert len(await outbox()) == 1


async def test_refund_after_cancel(events, outbox):
    event = booking_created(uuid.uuid4())
    await events(event)
    await events(booking_cancelled(event))
    assert [e.event_type for e in await outbox()] == ["payment.succeeded", "payment.refunded"]


async def test_cancel_before_charge_prevents_charge(events, outbox):
    event = booking_created(uuid.uuid4())
    await events(booking_cancelled(event))  # arrives first (out-of-order delivery)
    await events(event)
    assert await outbox() == []


async def test_payment_visibility(events, client, tokens):
    owner = uuid.uuid4()
    event = booking_created(owner)
    await events(event)
    booking_id = event.payload["booking_id"]

    assert (await client.get(f"/api/payments/booking/{booking_id}", headers=tokens.headers(owner))).status_code == 200
    assert (await client.get(f"/api/payments/booking/{booking_id}", headers=tokens.headers())).status_code == 404
    assert (await client.get(f"/api/payments/booking/{booking_id}", headers=tokens.headers(role="admin"))).status_code == 200
    assert (await client.get(f"/api/payments/{uuid.uuid4()}", headers=tokens.headers(owner))).status_code == 404
