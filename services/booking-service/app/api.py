import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from common.db import get_session
from common.errors import AUTH_RESPONSES, ErrorResponse
from common.schemas import Page, Pagination
from common.security import Principal, get_current_user

from .schemas import BookingCreate, BookingOut
from .service import BookingService

router = APIRouter(prefix="/api/bookings", tags=["bookings"])

NOT_FOUND = {404: {"model": ErrorResponse}}


def get_service(request: Request, session: AsyncSession = Depends(get_session)) -> BookingService:
    return BookingService(session, request.app.state.catalog, request.app.state.settings)


@router.post(
    "",
    response_model=BookingOut,
    status_code=status.HTTP_201_CREATED,
    summary="Book tickets",
    description=(
        "Reserves tickets in catalog-service (gRPC) and creates a booking in status `PENDING_PAYMENT`. "
        "Payment happens asynchronously (RabbitMQ saga); poll `GET /api/bookings/{id}` for `CONFIRMED`/`CANCELLED`.\n\n"
        "Send an `Idempotency-Key` header to make retries safe: the same key returns the same booking (200)."
    ),
    responses={
        **AUTH_RESPONSES,
        200: {"model": BookingOut, "description": "Idempotent replay"},
        404: {"model": ErrorResponse, "description": "Ticket category not found"},
        409: {"model": ErrorResponse, "description": "Sold out / event not on sale"},
        503: {"model": ErrorResponse, "description": "Catalog unavailable"},
        504: {"model": ErrorResponse, "description": "Catalog timeout"},
    },
)
async def create_booking(
    data: BookingCreate,
    response: Response,
    idempotency_key: str | None = Header(None, alias="Idempotency-Key", max_length=100),
    user: Principal = Depends(get_current_user),
    service: BookingService = Depends(get_service),
):
    booking, created = await service.create(user, data, idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
    return booking


@router.get("", response_model=Page[BookingOut], summary="My bookings (admin: all)", responses=AUTH_RESPONSES)
async def list_bookings(
    status_filter: Literal["PENDING_PAYMENT", "CONFIRMED", "CANCELLED"] | None = Query(None, alias="status"),
    user_id: uuid.UUID | None = Query(None, description="Admin only: filter by user"),
    page: Pagination = Depends(),
    user: Principal = Depends(get_current_user),
    service: BookingService = Depends(get_service),
) -> Page[BookingOut]:
    items, total = await service.list(user, status=status_filter, user_id=user_id, limit=page.limit, offset=page.offset)
    return Page(items=[BookingOut.model_validate(b) for b in items], total=total, limit=page.limit, offset=page.offset)


@router.get("/{booking_id}", response_model=BookingOut, summary="Booking details", responses={**AUTH_RESPONSES, **NOT_FOUND})
async def get_booking(booking_id: uuid.UUID, user: Principal = Depends(get_current_user), service: BookingService = Depends(get_service)):
    return await service.get_for_user(booking_id, user)


@router.post(
    "/{booking_id}/cancel",
    response_model=BookingOut,
    summary="Cancel booking (releases tickets, triggers refund if paid)",
    responses={**AUTH_RESPONSES, **NOT_FOUND, 409: {"model": ErrorResponse}},
)
async def cancel_booking(booking_id: uuid.UUID, user: Principal = Depends(get_current_user), service: BookingService = Depends(get_service)):
    return await service.cancel(booking_id, user)
