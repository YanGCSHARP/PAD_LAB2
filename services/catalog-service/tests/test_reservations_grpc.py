"""Tests of the gRPC reservation API through a real grpc.aio server/channel."""

import asyncio
import uuid

import grpc
import pytest
from conftest import category

from app.grpc_server import start_grpc_server
from common.protos import catalog_pb2, catalog_pb2_grpc


@pytest.fixture
async def stub(app):
    server, port = await start_grpc_server(app.state.db, "127.0.0.1:0")
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    yield catalog_pb2_grpc.CatalogReservationStub(channel)
    await channel.close()
    await server.stop(grace=None)


def reserve(stub, category_id: str, quantity: int, booking_id: str | None = None):
    return stub.ReserveTickets(
        catalog_pb2.ReserveTicketsRequest(booking_id=booking_id or str(uuid.uuid4()), category_id=category_id, quantity=quantity),
        metadata=(("x-request-id", "test-rid"),),
    )


def error_code(exc: grpc.aio.AioRpcError) -> str:
    return dict(exc.trailing_metadata() or ()).get("error-code", "")


async def available(client, event_id: str, name: str) -> int:
    return category((await client.get(f"/api/events/{event_id}")).json(), name)["available"]


async def test_reserve_decrements_availability(stub, client, event):
    reply = await reserve(stub, category(event, "Standard")["id"], 3)
    assert reply.status == "reserved"
    assert reply.total_price == "300.00"
    assert reply.event_title == "Jazz Night"
    assert await available(client, event["id"], "Standard") == 7


async def test_reserve_is_idempotent(stub, client, event):
    booking_id = str(uuid.uuid4())
    await reserve(stub, category(event, "Standard")["id"], 2, booking_id)
    await reserve(stub, category(event, "Standard")["id"], 2, booking_id)
    assert await available(client, event["id"], "Standard") == 8


async def test_sold_out(stub, event):
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await reserve(stub, category(event, "VIP")["id"], 3)
    assert exc.value.code() == grpc.StatusCode.FAILED_PRECONDITION
    assert error_code(exc.value) == "sold_out"


async def test_no_overselling_under_concurrency(stub, client, event):
    vip = category(event, "VIP")["id"]
    results = await asyncio.gather(*(reserve(stub, vip, 1) for _ in range(5)), return_exceptions=True)
    assert sum(1 for r in results if not isinstance(r, Exception)) == 2
    assert await available(client, event["id"], "VIP") == 0


async def test_unknown_category_and_bad_uuid(stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await reserve(stub, str(uuid.uuid4()), 1)
    assert exc.value.code() == grpc.StatusCode.NOT_FOUND
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await reserve(stub, "bad", 1)
    assert exc.value.code() == grpc.StatusCode.INVALID_ARGUMENT


async def test_release_returns_tickets_and_is_idempotent(stub, client, event):
    booking_id = str(uuid.uuid4())
    await reserve(stub, category(event, "Standard")["id"], 4, booking_id)
    for _ in range(2):
        reply = await stub.ReleaseTickets(catalog_pb2.ReservationRef(booking_id=booking_id))
        assert reply.status == "released"
    assert await available(client, event["id"], "Standard") == 10


async def test_confirm_then_release_rules(stub, event):
    booking_id = str(uuid.uuid4())
    await reserve(stub, category(event, "Standard")["id"], 1, booking_id)
    reply = await stub.ConfirmReservation(catalog_pb2.ReservationRef(booking_id=booking_id))
    assert reply.status == "confirmed"

    await stub.ReleaseTickets(catalog_pb2.ReservationRef(booking_id=booking_id))
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await stub.ConfirmReservation(catalog_pb2.ReservationRef(booking_id=booking_id))
    assert error_code(exc.value) == "reservation_released"


async def test_cancelled_event_not_on_sale(stub, client, admin, event):
    await client.patch(f"/api/events/{event['id']}", json={"status": "cancelled"}, headers=admin)
    with pytest.raises(grpc.aio.AioRpcError) as exc:
        await reserve(stub, category(event, "Standard")["id"], 1)
    assert error_code(exc.value) == "not_on_sale"


async def test_delete_event_with_bookings_conflict(stub, client, admin, event):
    await reserve(stub, category(event, "Standard")["id"], 1)
    response = await client.delete(f"/api/events/{event['id']}", headers=admin)
    assert response.status_code == 409
