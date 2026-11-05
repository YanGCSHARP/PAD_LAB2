import logging
import uuid

from common.db import Database, utcnow
from common.messaging import EventEnvelope, EventRouter
from common.outbox import claim_event

from .models import ProcessedEvent, Profile

logger = logging.getLogger(__name__)


async def on_user_registered(db: Database, event: EventEnvelope) -> None:
    payload = event.payload
    user_id = uuid.UUID(payload["user_id"])
    async with db.sessionmaker() as session:
        if not await claim_event(session, ProcessedEvent, event):
            return
        if await session.get(Profile, user_id) is None:
            session.add(
                Profile(
                    user_id=user_id,
                    email=payload["email"],
                    full_name=payload.get("full_name") or payload["email"],
                    role=payload.get("role", "user"),
                    created_at=utcnow(),
                    updated_at=utcnow(),
                )
            )
        await session.commit()
    logger.info("Profile provisioned", extra={"user_id": str(user_id)})


async def on_user_role_changed(db: Database, event: EventEnvelope) -> None:
    user_id = uuid.UUID(event.payload["user_id"])
    async with db.sessionmaker() as session:
        if not await claim_event(session, ProcessedEvent, event):
            return
        profile = await session.get(Profile, user_id)
        if profile is None:
            raise LookupError(f"Profile {user_id} not provisioned yet")  # retried by the bus
        profile.role = event.payload["role"]
        await session.commit()


def build_event_router(db: Database) -> EventRouter:
    router = EventRouter()
    router.on("user.registered", lambda e: on_user_registered(db, e))
    router.on("user.role_changed", lambda e: on_user_role_changed(db, e))
    return router
