import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db import get_session
from common.errors import AUTH_RESPONSES, ErrorResponse, ForbiddenError, NotFoundError
from common.schemas import Page, Pagination
from common.security import Principal, get_current_user, require_admin

from .models import Profile
from .schemas import ProfileOut, ProfileUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["users"])

NOT_FOUND = {404: {"model": ErrorResponse}}


async def load_profile(session: AsyncSession, user_id: uuid.UUID) -> Profile:
    profile = await session.get(Profile, user_id)
    if profile is None:
        raise NotFoundError("Profile not found (it may still be provisioning, retry in a moment)", code="profile_not_found")
    return profile


@router.get("/me", response_model=ProfileOut, summary="Current user's profile", responses={**AUTH_RESPONSES, **NOT_FOUND})
async def get_me(user: Principal = Depends(get_current_user), session: AsyncSession = Depends(get_session)) -> Profile:
    return await load_profile(session, user.user_id)


@router.patch("/me", response_model=ProfileOut, summary="Update own profile", responses={**AUTH_RESPONSES, **NOT_FOUND})
async def update_me(
    data: ProfileUpdate, user: Principal = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> Profile:
    profile = await load_profile(session, user.user_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    await session.commit()
    await session.refresh(profile)
    logger.info("Profile updated", extra={"user_id": str(user.user_id), "fields": list(data.model_fields_set)})
    return profile


@router.get("/{user_id}", response_model=ProfileOut, summary="Profile by id (self or admin)", responses={**AUTH_RESPONSES, **NOT_FOUND})
async def get_profile(
    user_id: uuid.UUID, user: Principal = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> Profile:
    if user.user_id != user_id and not user.is_admin:
        raise ForbiddenError("You can only view your own profile")
    return await load_profile(session, user_id)


@router.get("", response_model=Page[ProfileOut], summary="List profiles (admin only)", responses=AUTH_RESPONSES)
async def list_profiles(
    page: Pagination = Depends(),
    _: Principal = Depends(require_admin),
    session: AsyncSession = Depends(get_session),
) -> Page[ProfileOut]:
    total = await session.scalar(select(func.count()).select_from(Profile)) or 0
    rows = await session.scalars(select(Profile).order_by(Profile.created_at.desc()).limit(page.limit).offset(page.offset))
    return Page(items=[ProfileOut.model_validate(p) for p in rows], total=total, limit=page.limit, offset=page.offset)
