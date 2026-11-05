import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from common.db import get_session
from common.errors import AUTH_RESPONSES, ErrorResponse, NotFoundError
from common.schemas import Page, Pagination
from common.security import Principal, get_current_user

from .models import Payment

router = APIRouter(prefix="/api/payments", tags=["payments"])

NOT_FOUND = {404: {"model": ErrorResponse}}


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    booking_id: uuid.UUID
    user_id: uuid.UUID
    amount: Decimal
    currency: str
    status: str
    failure_reason: str | None
    provider_reference: str | None
    created_at: datetime
    updated_at: datetime


def _visible(payment: Payment | None, user: Principal) -> Payment:
    if payment is None or (payment.user_id != user.user_id and not user.is_admin):
        raise NotFoundError("Payment not found")
    return payment


@router.get("", response_model=Page[PaymentOut], summary="My payments (admin: all)", responses=AUTH_RESPONSES)
async def list_payments(
    page: Pagination = Depends(), user: Principal = Depends(get_current_user), session: AsyncSession = Depends(get_session)
) -> Page[PaymentOut]:
    query = select(Payment)
    if not user.is_admin:
        query = query.where(Payment.user_id == user.user_id)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.scalars(query.order_by(Payment.created_at.desc()).limit(page.limit).offset(page.offset))
    return Page(items=[PaymentOut.model_validate(p) for p in rows], total=total, limit=page.limit, offset=page.offset)


@router.get("/booking/{booking_id}", response_model=PaymentOut, summary="Payment of a booking", responses={**AUTH_RESPONSES, **NOT_FOUND})
async def payment_by_booking(
    booking_id: uuid.UUID, user: Principal = Depends(get_current_user), session: AsyncSession = Depends(get_session)
):
    return _visible(await session.scalar(select(Payment).where(Payment.booking_id == booking_id)), user)


@router.get("/{payment_id}", response_model=PaymentOut, summary="Payment details", responses={**AUTH_RESPONSES, **NOT_FOUND})
async def get_payment(payment_id: uuid.UUID, user: Principal = Depends(get_current_user), session: AsyncSession = Depends(get_session)):
    return _visible(await session.get(Payment, payment_id), user)
