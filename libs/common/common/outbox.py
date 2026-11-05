"""Transactional outbox + idempotent consumer helpers.

* A service writes its business change AND the event row (`outbox` table) in ONE DB transaction.
  The `OutboxRelay` background task publishes pending rows to RabbitMQ and marks them as published.
  This guarantees at-least-once delivery even if the broker is down at the moment of the change.
* Consumers record processed `event_id`s in `processed_events` inside the same transaction as
  their side effects, so redelivered events are ignored (exactly-once *effect*).
"""

import asyncio
import contextlib
import logging
import uuid
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import JSON, DateTime, Integer, String, Uuid, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from .db import Database, utcnow
from .log import request_id_ctx
from .messaging import EventEnvelope

logger = logging.getLogger("common.outbox")


class OutboxMixin:
    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)


class ProcessedEventMixin:
    __tablename__ = "processed_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def add_outbox_event(session: AsyncSession, model: type, event_type: str, payload: dict[str, Any]) -> Any:
    row = model(id=uuid.uuid4(), event_type=event_type, payload=payload, request_id=request_id_ctx.get(), created_at=utcnow())
    session.add(row)
    return row


async def claim_event(session: AsyncSession, model: type, envelope: EventEnvelope) -> bool:
    """Returns False if the event was already processed (duplicate delivery)."""
    if await session.get(model, envelope.event_id) is not None:
        logger.info("Duplicate event ignored", extra={"event_id": envelope.event_id, "event_type": envelope.event_type})
        return False
    session.add(model(event_id=envelope.event_id, event_type=envelope.event_type, processed_at=utcnow()))
    return True


class Publisher(Protocol):
    async def publish(self, event_type: str, payload: dict[str, Any], *, event_id: str | None = None,
                      request_id: str | None = None, occurred_at: datetime | None = None) -> None: ...


class OutboxRelay:
    def __init__(self, db: Database, model: type, bus: Publisher, *, interval: float = 0.5, batch_size: int = 100) -> None:
        self.db = db
        self.model = model
        self.bus = bus
        self.interval = interval
        self.batch_size = batch_size
        self._task: asyncio.Task | None = None

    async def run_once(self) -> int:
        model = self.model
        async with self.db.sessionmaker() as session, session.begin():
            rows = (
                await session.execute(
                    select(model)
                    .where(model.published_at.is_(None))
                    .order_by(model.created_at)
                    .limit(self.batch_size)
                    .with_for_update(skip_locked=True)
                )
            ).scalars().all()
            for row in rows:
                row.attempts += 1
                await self.bus.publish(
                    row.event_type, row.payload, event_id=str(row.id), request_id=row.request_id, occurred_at=row.created_at
                )
                row.published_at = utcnow()
        return len(rows)

    async def _loop(self) -> None:
        backoff = self.interval
        while True:
            try:
                published = await self.run_once()
                backoff = self.interval
                if published:
                    continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                backoff = min(backoff * 2, 10.0)
                logger.warning("Outbox relay failed, will retry", extra={"error": repr(exc), "retry_in_s": backoff})
            await asyncio.sleep(backoff)

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="outbox-relay")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
