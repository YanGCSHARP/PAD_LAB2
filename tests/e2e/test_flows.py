from datetime import UTC, datetime, timedelta

from conftest import wait_for


def create_event(api, admin, *, price: str, total: int) -> dict:
    venue = api.post("/api/venues", json={"name": "E2E Hall", "city": "Chisinau", "address": "Test 1", "capacity": 1000}, headers=admin)
    assert venue.status_code == 201, venue.text
    event = api.post(
        "/api/events",
        headers=admin,
        json={
            "venue_id": venue.json()["id"],
            "title": "E2E Concert",
            "starts_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            "ticket_categories": [{"name": "Standard", "price": price, "total": total}],
        },
    )
    assert event.status_code == 201, event.text
    return event.json()


def available(api, event_id: str) -> int:
    return api.get(f"/api/events/{event_id}").json()["ticket_categories"][0]["available"]


def booking_status(api, headers, booking_id: str) -> dict:
    return api.get(f"/api/bookings/{booking_id}", headers=headers).json()


def test_health_and_docs(api):
    assert api.get("/health").json()["status"] == "ok"
    assert "swagger-ui" in api.get("/docs").text
    assert api.get("/openapi/booking.json").json()["info"]["title"] == "Booking Service"


def test_profile_is_provisioned_via_rabbitmq(api, user):
    headers, account = user
    profile = wait_for(lambda: (r := api.get("/api/users/me", headers=headers)).status_code == 200 and r.json())
    assert profile["user_id"] == account["id"]


def test_happy_path_booking_confirmed(api, admin, user):
    headers, _ = user
    event = create_event(api, admin, price="200.00", total=10)
    category_id = event["ticket_categories"][0]["id"]

    response = api.post("/api/bookings", json={"category_id": category_id, "quantity": 3}, headers=headers)
    assert response.status_code == 201, response.text
    booking = response.json()
    assert booking["status"] == "PENDING_PAYMENT"
    assert booking["total_amount"] == "600.00"
    assert available(api, event["id"]) == 7  # reserved synchronously over gRPC

    confirmed = wait_for(lambda: (b := booking_status(api, headers, booking["id"]))["status"] == "CONFIRMED" and b)
    assert confirmed["payment_id"]

    payment = api.get(f"/api/payments/booking/{booking['id']}", headers=headers).json()
    assert payment["status"] == "SUCCEEDED"

    titles = wait_for(lambda: {n["title"] for n in api.get("/api/notifications", headers=headers).json()["items"]} >= {"Бронь подтверждена"}
                      and {n["title"] for n in api.get("/api/notifications", headers=headers).json()["items"]})
    assert "Добро пожаловать!" in titles

    dashboard = api.get("/api/dashboard", headers=headers).json()
    assert dashboard["degraded"] == []
    assert dashboard["recent_bookings"][0]["id"] == booking["id"]


def test_payment_declined_compensates(api, admin, user):
    headers, _ = user
    event = create_event(api, admin, price="6000.00", total=5)
    category_id = event["ticket_categories"][0]["id"]

    booking = api.post("/api/bookings", json={"category_id": category_id, "quantity": 2}, headers=headers).json()
    assert available(api, event["id"]) == 3

    cancelled = wait_for(lambda: (b := booking_status(api, headers, booking["id"]))["status"] == "CANCELLED" and b)
    assert cancelled["cancel_reason"].startswith("payment_failed")
    assert wait_for(lambda: available(api, event["id"]) == 5)  # tickets returned to the pool


def test_user_cancel_refunds(api, admin, user):
    headers, _ = user
    event = create_event(api, admin, price="100.00", total=5)
    booking = api.post("/api/bookings", json={"category_id": event["ticket_categories"][0]["id"], "quantity": 1}, headers=headers).json()
    wait_for(lambda: booking_status(api, headers, booking["id"])["status"] == "CONFIRMED")

    response = api.post(f"/api/bookings/{booking['id']}/cancel", headers=headers)
    assert response.json()["status"] == "CANCELLED"
    assert available(api, event["id"]) == 5
    wait_for(lambda: api.get(f"/api/payments/booking/{booking['id']}", headers=headers).json()["status"] == "REFUNDED")


def test_sold_out(api, admin, user):
    headers, _ = user
    event = create_event(api, admin, price="50.00", total=1)
    category_id = event["ticket_categories"][0]["id"]
    assert api.post("/api/bookings", json={"category_id": category_id, "quantity": 1}, headers=headers).status_code == 201
    response = api.post("/api/bookings", json={"category_id": category_id, "quantity": 1}, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "sold_out"


def test_idempotency_key(api, admin, user):
    headers, _ = user
    event = create_event(api, admin, price="50.00", total=5)
    body = {"category_id": event["ticket_categories"][0]["id"], "quantity": 1}
    first = api.post("/api/bookings", json=body, headers={**headers, "Idempotency-Key": "same-key"})
    second = api.post("/api/bookings", json=body, headers={**headers, "Idempotency-Key": "same-key"})
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert available(api, event["id"]) == 4


def test_errors_and_authorization(api, user):
    headers, _ = user
    assert api.get("/api/bookings").status_code == 401
    assert api.post("/api/events", json={}, headers=headers).status_code == 403
    assert api.get("/api/users", headers=headers).status_code == 403

    invalid = api.post("/api/auth/register", json={"email": "bad", "password": "1", "full_name": ""})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"

    missing = api.get("/api/events/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert "request_id" in missing.json()["error"]
    assert missing.headers["X-Request-ID"] == missing.json()["error"]["request_id"]
