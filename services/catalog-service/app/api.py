import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from common.db import get_session
from common.errors import AUTH_RESPONSES, PUBLIC_RESPONSES, ErrorResponse
from common.schemas import Page, Pagination
from common.security import Principal, require_admin

from .schemas import EventCategory, EventCreate, EventOut, EventUpdate, VenueCreate, VenueOut
from .service import CatalogService

router = APIRouter()

NOT_FOUND = {404: {"model": ErrorResponse}}
BAD_REQUEST = {400: {"model": ErrorResponse}}


def get_service(session: AsyncSession = Depends(get_session)) -> CatalogService:
    return CatalogService(session)


# ---- venues --------------------------------------------------------------------------------
@router.get("/api/venues", response_model=list[VenueOut], tags=["venues"], summary="List venues (public)")
async def list_venues(city: str | None = Query(None, max_length=100), service: CatalogService = Depends(get_service)):
    return await service.list_venues(city)


@router.get("/api/venues/{venue_id}", response_model=VenueOut, tags=["venues"], summary="Venue by id", responses=NOT_FOUND)
async def get_venue(venue_id: uuid.UUID, service: CatalogService = Depends(get_service)):
    return await service.get_venue(venue_id)


@router.post(
    "/api/venues", response_model=VenueOut, status_code=status.HTTP_201_CREATED, tags=["venues"],
    summary="Create venue (admin)", responses=AUTH_RESPONSES,
)
async def create_venue(data: VenueCreate, _: Principal = Depends(require_admin), service: CatalogService = Depends(get_service)):
    return await service.create_venue(data)


# ---- events --------------------------------------------------------------------------------
@router.get("/api/events", response_model=Page[EventOut], tags=["events"], summary="Search upcoming events (public)", responses=PUBLIC_RESPONSES)
async def list_events(
    q: str | None = Query(None, max_length=100, description="Search in title/description"),
    city: str | None = Query(None, max_length=100),
    category: EventCategory | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    include_past: bool = False,
    page: Pagination = Depends(),
    service: CatalogService = Depends(get_service),
) -> Page[EventOut]:
    items, total = await service.list_events(
        q=q, city=city, category=category, date_from=date_from, date_to=date_to,
        include_past=include_past, limit=page.limit, offset=page.offset,
    )
    return Page(items=[EventOut.model_validate(e) for e in items], total=total, limit=page.limit, offset=page.offset)


@router.get("/api/events/{event_id}", response_model=EventOut, tags=["events"], summary="Event details with ticket availability", responses=NOT_FOUND)
async def get_event(event_id: uuid.UUID, service: CatalogService = Depends(get_service)):
    return await service.get_event(event_id)


@router.post(
    "/api/events", response_model=EventOut, status_code=status.HTTP_201_CREATED, tags=["events"],
    summary="Create event with ticket categories (admin)", responses={**AUTH_RESPONSES, **NOT_FOUND, **BAD_REQUEST},
)
async def create_event(data: EventCreate, _: Principal = Depends(require_admin), service: CatalogService = Depends(get_service)):
    return await service.create_event(data)


@router.patch(
    "/api/events/{event_id}", response_model=EventOut, tags=["events"], summary="Update event (admin)",
    responses={**AUTH_RESPONSES, **NOT_FOUND, **BAD_REQUEST},
)
async def update_event(
    event_id: uuid.UUID, data: EventUpdate, _: Principal = Depends(require_admin), service: CatalogService = Depends(get_service)
):
    return await service.update_event(event_id, data)


@router.delete(
    "/api/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["events"], summary="Delete event without bookings (admin)",
    responses={**AUTH_RESPONSES, **NOT_FOUND, 409: {"model": ErrorResponse}},
)
async def delete_event(event_id: uuid.UUID, _: Principal = Depends(require_admin), service: CatalogService = Depends(get_service)):
    await service.delete_event(event_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
