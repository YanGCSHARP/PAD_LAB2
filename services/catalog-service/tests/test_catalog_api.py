import uuid
from datetime import UTC, datetime, timedelta

from conftest import category


async def test_public_listing_and_details(client, event):
    response = await client.get("/api/events", params={"city": "chisinau"})
    assert response.status_code == 200
    page = response.json()
    assert page["total"] == 1
    assert page["items"][0]["venue"]["name"] == "Hall"

    details = await client.get(f"/api/events/{event['id']}")
    assert details.json()["title"] == "Jazz Night"
    assert category(details.json(), "VIP")["available"] == 2


async def test_search_by_text(client, event):
    assert (await client.get("/api/events", params={"q": "jazz"})).json()["total"] == 1
    assert (await client.get("/api/events", params={"q": "opera"})).json()["total"] == 0


async def test_event_not_found(client):
    response = await client.get(f"/api/events/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_invalid_uuid_is_validation_error(client):
    response = await client.get("/api/events/not-a-uuid")
    assert response.status_code == 422


async def test_create_event_requires_admin(client, tokens):
    response = await client.post("/api/venues", json={"name": "x", "city": "y", "address": "z", "capacity": 1}, headers=tokens.headers())
    assert response.status_code == 403
    response = await client.post("/api/venues", json={"name": "x", "city": "y", "address": "z", "capacity": 1})
    assert response.status_code == 401


async def test_create_event_validation(client, admin, event):
    venue_id = event["venue"]["id"]
    base = {"venue_id": venue_id, "title": "X", "starts_at": (datetime.now(UTC) + timedelta(days=1)).isoformat()}

    response = await client.post("/api/events", json={**base, "ticket_categories": [{"name": "A", "price": "-1", "total": 1}]}, headers=admin)
    assert response.status_code == 422

    response = await client.post("/api/events", json={**base, "ticket_categories": [{"name": "A", "price": "10", "total": 1000}]}, headers=admin)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "capacity_exceeded"

    past = {**base, "starts_at": (datetime.now(UTC) - timedelta(days=1)).isoformat(), "ticket_categories": [{"name": "A", "price": "10", "total": 1}]}
    response = await client.post("/api/events", json=past, headers=admin)
    assert response.json()["error"]["code"] == "invalid_date"

    response = await client.post("/api/events", json={**base, "venue_id": str(uuid.uuid4()), "ticket_categories": [{"name": "A", "price": "10", "total": 1}]}, headers=admin)
    assert response.status_code == 404


async def test_update_and_cancel_event(client, admin, event):
    response = await client.patch(f"/api/events/{event['id']}", json={"status": "cancelled"}, headers=admin)
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


async def test_delete_event(client, admin, event):
    assert (await client.delete(f"/api/events/{event['id']}", headers=admin)).status_code == 204
    assert (await client.get(f"/api/events/{event['id']}")).status_code == 404
