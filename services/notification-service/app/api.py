from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from common.errors import AUTH_RESPONSES, ErrorResponse, NotFoundError
from common.schemas import Page, Pagination
from common.security import Principal, get_current_user

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: str = Field(validation_alias="_id")
    event_type: str
    channel: str
    title: str
    message: str
    status: str
    read: bool
    created_at: datetime


class UnreadCount(BaseModel):
    count: int


def repo(request: Request):
    return request.app.state.repo


@router.get("", response_model=Page[NotificationOut], summary="My notifications", responses=AUTH_RESPONSES)
async def list_notifications(
    unread_only: bool = Query(False),
    page: Pagination = Depends(),
    user: Principal = Depends(get_current_user),
    repository=Depends(repo),
) -> Page[NotificationOut]:
    items, total = await repository.list_for_user(str(user.user_id), unread_only, page.limit, page.offset)
    return Page(items=[NotificationOut.model_validate(i) for i in items], total=total, limit=page.limit, offset=page.offset)


@router.get("/unread-count", response_model=UnreadCount, summary="Number of unread notifications", responses=AUTH_RESPONSES)
async def unread_count(user: Principal = Depends(get_current_user), repository=Depends(repo)) -> UnreadCount:
    return UnreadCount(count=await repository.unread_count(str(user.user_id)))


@router.post(
    "/{notification_id}/read",
    response_model=UnreadCount,
    summary="Mark notification as read (returns remaining unread count)",
    responses={**AUTH_RESPONSES, 404: {"model": ErrorResponse}},
)
async def mark_read(notification_id: str, user: Principal = Depends(get_current_user), repository=Depends(repo)) -> UnreadCount:
    if not await repository.mark_read(str(user.user_id), notification_id):
        raise NotFoundError("Notification not found")
    return UnreadCount(count=await repository.unread_count(str(user.user_id)))
