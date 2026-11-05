"""gRPC client for catalog-service with deadline, circuit breaker and error mapping."""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

import grpc

from common.errors import (
    AppError,
    BadRequestError,
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    UpstreamError,
    UpstreamTimeoutError,
)
from common.log import request_id_ctx
from common.metrics import UPSTREAM_REQUESTS
from common.protos import catalog_pb2, catalog_pb2_grpc
from common.resilience import CircuitBreaker

logger = logging.getLogger(__name__)


@dataclass
class Reservation:
    booking_id: uuid.UUID
    event_id: uuid.UUID
    event_title: str
    category_id: uuid.UUID
    category_name: str
    quantity: int
    unit_price: Decimal
    total_price: Decimal
    status: str
    starts_at: datetime


class CatalogGateway(Protocol):
    async def reserve(self, booking_id: uuid.UUID, category_id: uuid.UUID, quantity: int) -> Reservation: ...

    async def confirm(self, booking_id: uuid.UUID) -> None: ...

    async def release(self, booking_id: uuid.UUID) -> None: ...

    async def close(self) -> None: ...


class CatalogGrpcClient:
    def __init__(self, target: str, timeout: float, breaker: CircuitBreaker) -> None:
        self.target = target
        self.timeout = timeout
        self.breaker = breaker
        self._channel: grpc.aio.Channel | None = None
        self._stub: catalog_pb2_grpc.CatalogReservationStub | None = None

    def _get_stub(self) -> catalog_pb2_grpc.CatalogReservationStub:
        # The channel is created lazily inside the running event loop.
        if self._stub is None:
            self._channel = grpc.aio.insecure_channel(self.target)
            self._stub = catalog_pb2_grpc.CatalogReservationStub(self._channel)
        return self._stub

    async def _call(self, method_name: str, request) -> catalog_pb2.ReservationReply:
        if not self.breaker.allow_request():
            UPSTREAM_REQUESTS.labels("catalog-grpc", "circuit_open").inc()
            raise ServiceUnavailableError("Catalog service is temporarily unavailable", code="circuit_open")
        method = getattr(self._get_stub(), method_name)
        try:
            reply = await method(request, timeout=self.timeout, metadata=(("x-request-id", request_id_ctx.get()),))
        except grpc.aio.AioRpcError as exc:
            raise self._map_error(method_name, exc) from exc
        self.breaker.record_success()
        UPSTREAM_REQUESTS.labels("catalog-grpc", "ok").inc()
        return reply

    def _map_error(self, method_name: str, exc: grpc.aio.AioRpcError) -> AppError:
        code = exc.code()
        error_code = dict(exc.trailing_metadata() or ()).get("error-code")
        details = exc.details() or "Catalog error"
        business = {
            grpc.StatusCode.NOT_FOUND: NotFoundError,
            grpc.StatusCode.FAILED_PRECONDITION: ConflictError,
            grpc.StatusCode.INVALID_ARGUMENT: BadRequestError,
        }
        if code in business:
            self.breaker.record_success()  # the service is healthy, the request was just rejected
            UPSTREAM_REQUESTS.labels("catalog-grpc", "rejected").inc()
            return business[code](details, code=error_code)

        self.breaker.record_failure()
        logger.warning("Catalog gRPC call failed", extra={"rpc": method_name, "grpc_status": code.name, "details": details})
        if code == grpc.StatusCode.DEADLINE_EXCEEDED:
            UPSTREAM_REQUESTS.labels("catalog-grpc", "timeout").inc()
            return UpstreamTimeoutError("Catalog service did not respond in time")
        if code == grpc.StatusCode.UNAVAILABLE:
            UPSTREAM_REQUESTS.labels("catalog-grpc", "unavailable").inc()
            return ServiceUnavailableError("Catalog service is unavailable")
        UPSTREAM_REQUESTS.labels("catalog-grpc", "error").inc()
        return UpstreamError("Catalog service error")

    async def reserve(self, booking_id: uuid.UUID, category_id: uuid.UUID, quantity: int) -> Reservation:
        reply = await self._call(
            "ReserveTickets",
            catalog_pb2.ReserveTicketsRequest(booking_id=str(booking_id), category_id=str(category_id), quantity=quantity),
        )
        return Reservation(
            booking_id=uuid.UUID(reply.booking_id),
            event_id=uuid.UUID(reply.event_id),
            event_title=reply.event_title,
            category_id=uuid.UUID(reply.category_id),
            category_name=reply.category_name,
            quantity=reply.quantity,
            unit_price=Decimal(reply.unit_price),
            total_price=Decimal(reply.total_price),
            status=reply.status,
            starts_at=datetime.fromisoformat(reply.starts_at),
        )

    async def confirm(self, booking_id: uuid.UUID) -> None:
        await self._call("ConfirmReservation", catalog_pb2.ReservationRef(booking_id=str(booking_id)))

    async def release(self, booking_id: uuid.UUID) -> None:
        await self._call("ReleaseTickets", catalog_pb2.ReservationRef(booking_id=str(booking_id)))

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
