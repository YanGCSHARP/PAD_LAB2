"""gRPC server: internal reservation API consumed by booking-service."""

import functools
import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import grpc

from common.db import Database
from common.errors import AppError, BadRequestError
from common.log import request_id_ctx
from common.protos import catalog_pb2, catalog_pb2_grpc

from .service import ReservationInfo, ReservationService

logger = logging.getLogger(__name__)

_STATUS_BY_HTTP = {
    400: grpc.StatusCode.INVALID_ARGUMENT,
    404: grpc.StatusCode.NOT_FOUND,
    409: grpc.StatusCode.FAILED_PRECONDITION,
}


def to_reply(info: ReservationInfo) -> catalog_pb2.ReservationReply:
    return catalog_pb2.ReservationReply(
        booking_id=str(info.booking_id),
        event_id=str(info.event_id),
        event_title=info.event_title,
        category_id=str(info.category_id),
        category_name=info.category_name,
        quantity=info.quantity,
        unit_price=f"{info.unit_price:.2f}",
        total_price=f"{info.total_price:.2f}",
        status=info.status,
        starts_at=info.starts_at.isoformat(),
    )


def parse_uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise BadRequestError(f"{field} must be a UUID", code="invalid_argument") from exc


def grpc_endpoint(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """Sets request-id from metadata, logs the call and maps AppError -> gRPC status (+ `error-code` trailer)."""

    @functools.wraps(func)
    async def wrapper(self: "CatalogReservationServicer", request: Any, context: grpc.aio.ServicerContext) -> Any:
        metadata = dict(context.invocation_metadata() or ())
        token = request_id_ctx.set(str(metadata.get("x-request-id") or uuid.uuid4().hex))
        try:
            reply = await func(self, request, context)
            logger.info("gRPC %s ok", func.__name__, extra={"rpc": func.__name__, "booking_id": request.booking_id})
            return reply
        except AppError as exc:
            logger.info("gRPC %s rejected: %s", func.__name__, exc.message, extra={"rpc": func.__name__, "error_code": exc.code})
            context.set_trailing_metadata((("error-code", exc.code),))
            await context.abort(_STATUS_BY_HTTP.get(exc.status_code, grpc.StatusCode.INTERNAL), exc.message)
        except Exception:
            logger.exception("gRPC %s failed", func.__name__)
            await context.abort(grpc.StatusCode.INTERNAL, "Internal error")
        finally:
            request_id_ctx.reset(token)

    return wrapper


class CatalogReservationServicer(catalog_pb2_grpc.CatalogReservationServicer):
    def __init__(self, db: Database) -> None:
        self.db = db

    @grpc_endpoint
    async def ReserveTickets(self, request, context):  # noqa: N802 - gRPC naming
        booking_id = parse_uuid(request.booking_id, "booking_id")
        category_id = parse_uuid(request.category_id, "category_id")
        async with self.db.sessionmaker() as session:
            return to_reply(await ReservationService(session).reserve(booking_id, category_id, request.quantity))

    @grpc_endpoint
    async def ConfirmReservation(self, request, context):  # noqa: N802
        async with self.db.sessionmaker() as session:
            return to_reply(await ReservationService(session).confirm(parse_uuid(request.booking_id, "booking_id")))

    @grpc_endpoint
    async def ReleaseTickets(self, request, context):  # noqa: N802
        booking_id = parse_uuid(request.booking_id, "booking_id")
        async with self.db.sessionmaker() as session:
            info = await ReservationService(session).release(booking_id)
        if info is None:  # nothing was reserved -> nothing to release (idempotent success)
            return catalog_pb2.ReservationReply(booking_id=str(booking_id), status="released")
        return to_reply(info)


async def start_grpc_server(db: Database, address: str) -> tuple[grpc.aio.Server, int]:
    server = grpc.aio.server()
    catalog_pb2_grpc.add_CatalogReservationServicer_to_server(CatalogReservationServicer(db), server)
    port = server.add_insecure_port(address)
    await server.start()
    logger.info("gRPC server started", extra={"address": address, "port": port})
    return server, port
